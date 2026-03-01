import logging
from pathlib import Path

import click

from fcc_ca_ads.config import CA_TARGET_DMAS
from fcc_ca_ads.client import OpifClient
from fcc_ca_ads.db.connection import get_connection
from fcc_ca_ads.db import queries
from fcc_ca_ads.discover import discover_stations, save_stations

logger = logging.getLogger(__name__)

DEFAULT_DB = Path("data/ads.db")
DEFAULT_STATIONS = Path("data/stations.json")
DEFAULT_RAW = Path("data/raw")


@click.group()
@click.option("--db", type=click.Path(), default=str(DEFAULT_DB), help="SQLite database path")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, db, verbose):
    """FCC California Political Ad Extraction CLI."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db
    ctx.obj["conn"] = get_connection(db)


@cli.command()
@click.pass_context
def status(ctx):
    """Show database status."""
    conn = ctx.obj["conn"]
    stations = queries.list_stations(conn)
    click.echo(f"Stations: {len(stations)}")
    for s in stations:
        click.echo(f"  {s['call_sign']} ({s['market']})")

    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    downloaded = conn.execute(
        "SELECT COUNT(*) FROM files WHERE downloaded_at IS NOT NULL"
    ).fetchone()[0]
    extracted = conn.execute(
        "SELECT COUNT(DISTINCT file_id) FROM extractions"
    ).fetchone()[0]
    click.echo(f"Files: {file_count} total, {downloaded} downloaded, {extracted} extracted")


@cli.command()
@click.option("--state", default="CA")
@click.option("--output", type=click.Path(), default=str(DEFAULT_STATIONS))
@click.pass_context
def discover(ctx, state, output):
    """Discover TV stations from FCC facility search."""
    conn = ctx.obj["conn"]
    client = OpifClient()
    stations = discover_stations(client, state=state, target_dmas=CA_TARGET_DMAS)
    save_stations(stations, Path(output))
    for s in stations:
        queries.upsert_station(
            conn, s.entity_id, s.call_sign, s.market, s.city, s.state, s.service_type
        )
    click.echo(f"Discovered {len(stations)} stations, saved to {output}")


@cli.command("load-stations")
@click.option("--input", "input_path", type=click.Path(exists=True),
              default=str(DEFAULT_STATIONS), help="JSON file with station data")
@click.pass_context
def load_stations_cmd(ctx, input_path):
    """Load stations from a JSON seed file into the database."""
    from fcc_ca_ads.discover import load_stations

    conn = ctx.obj["conn"]
    stations = load_stations(Path(input_path))
    for s in stations:
        queries.upsert_station(
            conn, s.entity_id, s.call_sign, s.market, s.city, s.state, s.service_type
        )
    click.echo(f"Loaded {len(stations)} stations from {input_path}")


@cli.command()
@click.option("--station", help="Single station call sign")
@click.option("--all", "all_stations", is_flag=True, help="Download for all stations")
@click.option("--since", default="2025-01-01", help="Start date for file history (YYYY-MM-DD)")
@click.option("--until", "until_date", default=None, help="End date (default: today)")
@click.option("--limit", "max_files", default=100, help="Max files per station")
@click.option("--dry-run", is_flag=True, help="List files without downloading")
@click.option("--workers", default=1, type=int, help="Number of concurrent download threads")
@click.pass_context
def download(ctx, station, all_stations, since, until_date, max_files, dry_run, workers):
    """Download political file PDFs via file history API."""
    from datetime import date

    db_path = ctx.obj["db_path"]
    conn = ctx.obj["conn"]
    client = OpifClient()
    end = until_date or date.today().isoformat()

    if station:
        s = queries.get_station_by_call_sign(conn, station)
        if not s:
            click.echo(f"Station {station} not found in database. Run 'discover' first.")
            return
        count = _download_station(
            client, db_path, s["entity_id"], s["call_sign"],
            since, end, max_files, dry_run, workers,
        )
        click.echo(f"{'Found' if dry_run else 'Downloaded'} {count} files for {station}")
    elif all_stations:
        stations = queries.list_stations(conn)
        total = 0
        with click.progressbar(stations, label="Downloading", show_pos=True) as bar:
            for s in bar:
                count = _download_station(
                    client, db_path, s["entity_id"], s["call_sign"],
                    since, end, max_files, dry_run, workers,
                )
                total += count
        click.echo(
            f"{'Found' if dry_run else 'Downloaded'} {total} files across {len(stations)} stations"
        )
    else:
        click.echo("Specify --station or --all")


def _download_station(client, db_path, entity_id, call_sign, since, until, max_files,
                      dry_run=False, workers=1):
    from fcc_ca_ads.download import download_pdf, sha256_file

    conn = get_connection(db_path)

    # Use file history API — more reliable than folder tree walk
    history = client.get_file_history(entity_id, since, until, count=max_files)
    if not history:
        logger.info("No file history for %s", call_sign)
        return 0

    # Filter to downloadable items
    items = []
    count = 0
    for h in history:
        fid = h.get("file_id", "")
        if queries.get_file(conn, fid):
            continue
        fname = h.get("file_name", "unknown")
        fmid = h.get("file_manager_id", "")
        folder_id = h.get("folder_id", "")
        fsize = h.get("file_size", 0)
        fpath = h.get("file_folder_path", "")

        # Only process political files
        if "political" not in fpath.lower():
            continue

        if dry_run:
            click.echo(f"  [dry-run] {call_sign}: {fname} ({fpath})")
            count += 1
            continue

        items.append({
            "fid": fid, "fname": fname, "fmid": fmid,
            "folder_id": folder_id, "fsize": fsize, "fpath": fpath,
        })

    if dry_run or not items:
        return count

    def _process_file(item):
        thread_conn = get_connection(db_path)
        dest = DEFAULT_RAW / call_sign / f"{item['fmid']}.pdf"
        try:
            download_pdf(client, item["folder_id"], item["fmid"], dest)
            sha = sha256_file(dest)
            queries.upsert_file(
                thread_conn,
                file_id=item["fid"],
                entity_id=entity_id,
                file_manager_id=item["fmid"],
                file_name=item["fname"],
                folder_id=item["folder_id"],
                file_size=item["fsize"],
                folder_path=item["fpath"],
            )
            queries.mark_downloaded(thread_conn, item["fid"], sha256=sha, local_path=str(dest))
            click.echo(f"  {call_sign}: {item['fname']}")
            return 1
        except Exception as exc:
            logger.error("Failed to download %s/%s: %s", call_sign, item["fname"], exc)
            return 0

    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = pool.map(_process_file, items)
        return sum(results)

    # Serial path — reuse the connection we already opened
    for item in items:
        dest = DEFAULT_RAW / call_sign / f"{item['fmid']}.pdf"
        try:
            download_pdf(client, item["folder_id"], item["fmid"], dest)
            sha = sha256_file(dest)
            queries.upsert_file(
                conn,
                file_id=item["fid"],
                entity_id=entity_id,
                file_manager_id=item["fmid"],
                file_name=item["fname"],
                folder_id=item["folder_id"],
                file_size=item["fsize"],
                folder_path=item["fpath"],
            )
            queries.mark_downloaded(conn, item["fid"], sha256=sha, local_path=str(dest))
            count += 1
            click.echo(f"  {call_sign}: {item['fname']}")
        except Exception as exc:
            logger.error("Failed to download %s/%s: %s", call_sign, item["fname"], exc)
    return count


@cli.command()
@click.pass_context
def extract(ctx):
    """Extract fields from downloaded PDFs."""
    from fcc_ca_ads.extract import extract_pdf_text
    from fcc_ca_ads.fields import extract_all_fields

    conn = ctx.obj["conn"]
    files = conn.execute(
        """
        SELECT f.* FROM files f
        WHERE f.downloaded_at IS NOT NULL
        AND f.file_id NOT IN (SELECT DISTINCT file_id FROM extractions)
        """
    ).fetchall()
    count = 0
    with click.progressbar(files, label="Extracting", show_pos=True) as bar:
        for f in bar:
            path = Path(f["local_path"]) if f["local_path"] else None
            if not path or not path.exists():
                continue
            result = extract_pdf_text(path)
            for page_num, page_text in enumerate(result.pages):
                matches = extract_all_fields(page_text, page=page_num)
                for m in matches:
                    queries.insert_extraction(
                        conn,
                        file_id=f["file_id"],
                        field_name=m.field_name,
                        field_value=m.value,
                        confidence=m.confidence,
                        page_number=m.page_number,
                    )
            queries.mark_ocr_done(conn, f["file_id"], ocr_needed=result.ocr_used)
            count += 1
    click.echo(f"Extracted fields from {count} files")


_EXPORT_COLUMNS = [
    "call_sign", "market", "file_name", "field_name",
    "field_value", "confidence", "page_number", "extracted_at",
]


@cli.command()
@click.option("--candidate", help="Search by candidate name")
@click.option("--advertiser", help="Search by advertiser name")
@click.option("--market", help="Filter by market/DMA")
@click.option("--since", help="Filter by download date (YYYY-MM-DD)")
@click.option("--format", "fmt", type=click.Choice(["table", "csv", "json"]),
              default="table", help="Output format")
@click.pass_context
def query(ctx, candidate, advertiser, market, since, fmt):
    """Query extracted ad data."""
    conn = ctx.obj["conn"]
    if candidate:
        results = queries.query_extractions(
            conn, field_name="candidate", value_like=f"%{candidate}%",
            market=market, since=since,
        )
    elif advertiser:
        results = queries.query_extractions(
            conn, field_name="advertiser", value_like=f"%{advertiser}%",
            market=market, since=since,
        )
    else:
        results = queries.query_extractions(conn, market=market, since=since)

    if fmt == "json":
        import json
        rows = [
            {col: r[col] for col in _EXPORT_COLUMNS}
            for r in results
        ]
        click.echo(json.dumps(rows, indent=2))
        return

    if not results:
        click.echo("No results found.")
        return

    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_EXPORT_COLUMNS)
        writer.writeheader()
        for r in results:
            writer.writerow({col: r[col] for col in _EXPORT_COLUMNS})
        click.echo(buf.getvalue(), nl=False)
        return

    for r in results:
        click.echo(
            f"{r['call_sign']} | {r['field_name']}: {r['field_value']} "
            f"({r['confidence']}) | file: {r['file_name']}"
        )
