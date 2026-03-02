import logging
from datetime import datetime
from pathlib import Path

import click

from fcc_ad_tracker.config import DEFAULT_TARGET_DMAS, OpifConfig
from fcc_ad_tracker.client import OpifClient
from fcc_ad_tracker.db.connection import get_connection
from fcc_ad_tracker.db import queries
from fcc_ad_tracker.discover import discover_stations, save_stations
from fcc_ad_tracker.scratchpad import Scratchpad

logger = logging.getLogger(__name__)

DEFAULT_DB = Path("data/ads.db")
DEFAULT_STATIONS = Path("data/stations.json")
DEFAULT_RAW = Path("data/raw")
DEFAULT_LOG_DIR = Path("data/logs")
DEFAULT_CACHE_DIR = Path("data/cache")


@click.group()
@click.option("--db", type=click.Path(), default=str(DEFAULT_DB), help="SQLite database path")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.option("--no-cache", is_flag=True, help="Disable API response cache")
@click.option("--quiet", "-q", is_flag=True, help="Suppress log path message")
@click.option("--log-dir", type=click.Path(), default=None,
              help="Directory for scratchpad logs (default: data/logs/)")
@click.pass_context
def cli(ctx, db, verbose, no_cache, quiet, log_dir):
    """FCC Political Ad Tracker CLI."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db
    ctx.obj["conn"] = get_connection(db)
    ctx.obj["no_cache"] = no_cache
    ctx.obj["quiet"] = quiet

    # Scratchpad lifecycle — only when --log-dir is set
    if log_dir is not None:
        log_path = Path(log_dir)
        cmd_name = ctx.invoked_subcommand or "cli"
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        sp_path = log_path / f"{ts}_{cmd_name}.jsonl"
        sp = Scratchpad(sp_path)
        ctx.obj["scratchpad"] = sp

        def _close_scratchpad():
            sp.close()
            if not quiet:
                click.echo(f"Log: {sp_path}", err=True)

        ctx.call_on_close(_close_scratchpad)


def _make_client(ctx) -> OpifClient:
    no_cache = ctx.obj.get("no_cache", False)
    cache_dir = None if no_cache else DEFAULT_CACHE_DIR
    config = OpifConfig(cache_dir=cache_dir)
    sp = ctx.obj.get("scratchpad")
    return OpifClient(config, scratchpad=sp)


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
    client = _make_client(ctx)
    stations = discover_stations(client, state=state, target_dmas=DEFAULT_TARGET_DMAS)
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
    from fcc_ad_tracker.discover import load_stations

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
    client = _make_client(ctx)
    scratchpad = ctx.obj.get("scratchpad")
    end = until_date or date.today().isoformat()

    if station:
        s = queries.get_station_by_call_sign(conn, station)
        if not s:
            click.echo(f"Station {station} not found in database. Run 'discover' first.")
            return
        count = _download_station(
            client, db_path, s["entity_id"], s["call_sign"],
            since, end, max_files, dry_run, workers,
            scratchpad=scratchpad,
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
                    scratchpad=scratchpad,
                )
                total += count
        click.echo(
            f"{'Found' if dry_run else 'Downloaded'} {total} files across {len(stations)} stations"
        )
    else:
        click.echo("Specify --station or --all")


def _download_station(client, db_path, entity_id, call_sign, since, until, max_files,
                      dry_run=False, workers=1, scratchpad=None):
    from fcc_ad_tracker.download import download_pdf, sha256_file

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

    from fcc_ad_tracker.classify import classify_file_type

    def _process_file(item):
        thread_conn = get_connection(db_path)
        dest = DEFAULT_RAW / call_sign / f"{item['fmid']}.pdf"
        try:
            download_pdf(client, item["folder_id"], item["fmid"], dest)
            sha = sha256_file(dest)

            # SHA-256 dedup: skip if identical file already downloaded
            existing = queries.file_exists_by_sha256(thread_conn, sha)
            if existing:
                logger.info("Skipping %s (duplicate of %s)", item["fname"], existing["file_id"])
                dest.unlink(missing_ok=True)
                return 0

            file_type = classify_file_type(item["fname"], item["fpath"])
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
            queries.set_file_type(thread_conn, item["fid"], file_type)
            if scratchpad:
                scratchpad.log(
                    "download", file_id=item["fid"],
                    call_sign=call_sign, sha256=sha, local_path=str(dest),
                )
            click.echo(f"  {call_sign}: {item['fname']} [{file_type}]")
            return 1
        except Exception as exc:
            logger.error("Failed to download %s/%s: %s", call_sign, item["fname"], exc)
            if scratchpad:
                scratchpad.log(
                    "error", operation="download",
                    error_message=str(exc), file_id=item["fid"],
                    call_sign=call_sign,
                )
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

            # SHA-256 dedup: skip if identical file already downloaded
            existing = queries.file_exists_by_sha256(conn, sha)
            if existing:
                logger.info("Skipping %s (duplicate of %s)", item["fname"], existing["file_id"])
                dest.unlink(missing_ok=True)
                continue

            file_type = classify_file_type(item["fname"], item["fpath"])
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
            queries.set_file_type(conn, item["fid"], file_type)
            if scratchpad:
                scratchpad.log(
                    "download", file_id=item["fid"],
                    call_sign=call_sign, sha256=sha, local_path=str(dest),
                )
            count += 1
            click.echo(f"  {call_sign}: {item['fname']} [{file_type}]")
        except Exception as exc:
            logger.error("Failed to download %s/%s: %s", call_sign, item["fname"], exc)
            if scratchpad:
                scratchpad.log(
                    "error", operation="download",
                    error_message=str(exc), file_id=item["fid"],
                    call_sign=call_sign,
                )
    return count


@cli.command()
@click.pass_context
def extract(ctx):
    """Extract fields from downloaded PDFs."""
    from fcc_ad_tracker.extract import extract_pdf_text
    from fcc_ad_tracker.fields import extract_all_fields, FieldMatch, CONFIDENCE_ORDER
    from fcc_ad_tracker.contracts import extract_contract_meta
    from fcc_ad_tracker.line_items import parse_line_items
    from fcc_ad_tracker.classify import classify_file_type, is_terms_and_conditions

    conn = ctx.obj["conn"]
    scratchpad = ctx.obj.get("scratchpad")
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

            # Content-based file type classification (refine from filename-based)
            if result.pages:
                content_type = classify_file_type(
                    f["file_name"], f["folder_path"] or "",
                    page0_text=result.pages[0],
                )
                if content_type != "unknown":
                    queries.set_file_type(conn, f["file_id"], content_type)

            # Per-document extraction: find best match across all pages
            # Skip Terms & Conditions pages
            best: dict[str, FieldMatch] = {}
            for page_num, page_text in enumerate(result.pages):
                if is_terms_and_conditions(page_text):
                    continue
                matches = extract_all_fields(page_text, page=page_num)
                for m in matches:
                    if m.field_name not in best:
                        best[m.field_name] = m
                    elif CONFIDENCE_ORDER[m.confidence] < CONFIDENCE_ORDER[best[m.field_name].confidence]:
                        best[m.field_name] = m

            for m in best.values():
                queries.insert_extraction(
                    conn,
                    file_id=f["file_id"],
                    field_name=m.field_name,
                    field_value=m.value,
                    confidence=m.confidence,
                    page_number=m.page_number,
                )

            # Contract-level extraction across full document text
            full_text = "\n".join(result.pages)
            meta = extract_contract_meta(full_text)
            if meta.contract_number:
                entity_id = f["entity_id"]
                contract_id = f"{entity_id}:{meta.contract_number}"

                # Get advertiser/candidate from field extraction if contract doesn't have them
                advertiser = best.get("advertiser")
                candidate = best.get("candidate")

                # Only upsert if this revision >= existing revision
                existing = queries.get_contract(conn, contract_id)
                if not existing or meta.revision_number >= existing["revision_number"]:
                    queries.upsert_contract(
                        conn,
                        contract_id=contract_id,
                        entity_id=entity_id,
                        contract_number=meta.contract_number,
                        advertiser=advertiser.value if advertiser else None,
                        candidate=candidate.value if candidate else None,
                        agency=meta.agency,
                        contract_start=meta.contract_start,
                        contract_end=meta.contract_end,
                        total_spots=meta.total_spots,
                        gross_total=meta.gross_total,
                        agency_commission=meta.agency_commission,
                        net_total=meta.net_total,
                        demographic=meta.demographic,
                        revision_number=meta.revision_number,
                        latest_file_id=f["file_id"],
                    )

            # Line-item extraction across all pages (skip T&C pages)
            contract_num = meta.contract_number if meta.contract_number else None
            for page_num, page_text in enumerate(result.pages):
                if is_terms_and_conditions(page_text):
                    continue
                for li in parse_line_items(page_text):
                    queries.insert_line_item(
                        conn,
                        file_id=f["file_id"],
                        contract_number=contract_num,
                        line_number=li.line_number,
                        channel=li.channel,
                        show_name=li.show_name,
                        time_slot=li.time_slot,
                        spot_length=li.spot_length,
                        rate_type=li.rate_type,
                        spots=li.spots,
                        rate_per_spot=li.rate_per_spot,
                        line_total=li.line_total,
                        start_date=li.start_date,
                        end_date=li.end_date,
                        page_number=page_num,
                    )

            queries.mark_ocr_done(conn, f["file_id"], ocr_needed=result.ocr_used)
            if scratchpad:
                scratchpad.log(
                    "extraction",
                    file_id=f["file_id"],
                    fields_found=list(best.keys()),
                    contract_number=contract_num,
                    line_items_count=sum(
                        len(parse_line_items(p))
                        for p in result.pages
                        if not is_terms_and_conditions(p)
                    ),
                )
            count += 1
    click.echo(f"Extracted fields from {count} files")


_CONTRACT_COLUMNS = [
    "call_sign", "market", "contract_number", "advertiser", "candidate",
    "agency", "contract_start", "contract_end", "total_spots",
    "gross_total", "agency_commission", "net_total", "revision_number",
]


@cli.command()
@click.option("--candidate", help="Filter by candidate name")
@click.option("--advertiser", help="Filter by advertiser name")
@click.option("--market", help="Filter by market/DMA")
@click.option("--district", help="Filter by congressional district (e.g. CA-27, TX-22)")
@click.option("--format", "fmt", type=click.Choice(["table", "csv", "json"]),
              default="table", help="Output format")
@click.pass_context
def contracts(ctx, candidate, advertiser, market, district, fmt):
    """List contracts with totals."""
    conn = ctx.obj["conn"]

    if district:
        results = queries.query_contracts_by_district(
            conn, district, candidate=candidate, advertiser=advertiser,
        )
        _DISTRICT_COLS = [
            "district", "dma_name", "weight", "call_sign", "market",
            "contract_number", "advertiser", "candidate",
            "gross_total", "net_total", "estimated_gross", "estimated_net",
        ]
        if fmt == "json":
            import json
            rows = [{col: r[col] for col in _DISTRICT_COLS} for r in results]
            click.echo(json.dumps(rows, indent=2))
            return
        if not results:
            click.echo(f"No contracts found for {district}.")
            return
        if fmt == "csv":
            import csv
            import io
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=_DISTRICT_COLS)
            writer.writeheader()
            for r in results:
                writer.writerow({col: r[col] for col in _DISTRICT_COLS})
            click.echo(buf.getvalue(), nl=False)
            return
        for r in results:
            eg = f"${r['estimated_gross']:,.2f}" if r["estimated_gross"] else "N/A"
            en = f"${r['estimated_net']:,.2f}" if r["estimated_net"] else "N/A"
            w = f"{r['weight'] * 100:.1f}%"
            click.echo(
                f"{r['call_sign']} ({r['dma_name']}, {w}) "
                f"| {r['contract_number']} | {r['candidate'] or 'N/A'} "
                f"| est_gross={eg} est_net={en}"
            )
        return

    results = queries.query_contracts(
        conn, candidate=candidate, advertiser=advertiser, market=market,
    )

    if fmt == "json":
        import json
        rows = [
            {col: r[col] for col in _CONTRACT_COLUMNS}
            for r in results
        ]
        click.echo(json.dumps(rows, indent=2))
        return

    if not results:
        click.echo("No contracts found.")
        return

    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_CONTRACT_COLUMNS)
        writer.writeheader()
        for r in results:
            writer.writerow({col: r[col] for col in _CONTRACT_COLUMNS})
        click.echo(buf.getvalue(), nl=False)
        return

    for r in results:
        gross = f"${r['gross_total']:,.2f}" if r["gross_total"] else "N/A"
        net = f"${r['net_total']:,.2f}" if r["net_total"] else "N/A"
        spots = r["total_spots"] or "N/A"
        click.echo(
            f"{r['call_sign']} | {r['contract_number']} "
            f"| {r['advertiser'] or 'N/A'} "
            f"| {r['candidate'] or 'N/A'} "
            f"| gross={gross} net={net} spots={spots}"
        )


@cli.command()
@click.option("--candidate", help="Filter by candidate name")
@click.option("--station", help="Filter by station call sign")
@click.option("--show", "show_name", help="Filter by show name")
@click.option("--district", help="Filter by congressional district (e.g. CA-27)")
@click.option("--state", "state_filter", help="Filter by state (e.g. CA, TX)")
@click.option("--by", "group_by", type=click.Choice(["station", "show", "district"]),
              default="station", help="Group results by station, show, or district")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def summary(ctx, candidate, station, show_name, district, state_filter, group_by, fmt):
    """Summarize ad spend by station, show, or district."""
    import json as json_mod

    conn = ctx.obj["conn"]

    if group_by == "district" or district:
        if district:
            # Single district detail view
            results = queries.query_contracts_by_district(
                conn, district, candidate=candidate,
            )
            if fmt == "json":
                rows = [
                    {
                        "district": r["district"],
                        "dma_name": r["dma_name"],
                        "weight": r["weight"],
                        "candidate": r["candidate"],
                        "estimated_gross": r["estimated_gross"],
                        "estimated_net": r["estimated_net"],
                    }
                    for r in results
                ]
                click.echo(json_mod.dumps(rows, indent=2))
                return
            if not results:
                click.echo(f"No ad exposure found for {district}.")
                return
            # Show DMA weight breakdown
            weights = queries.district_dma_weights(conn, district)
            weight_parts = [f"{w['weight'] * 100:.1f}% in {w['dma_name']}" for w in weights]
            click.echo(f"{district} ({' + '.join(weight_parts)})")
            total_eg = sum(r["estimated_gross"] or 0 for r in results)
            total_en = sum(r["estimated_net"] or 0 for r in results)
            click.echo(f"  estimated_gross=${total_eg:,.2f} estimated_net=${total_en:,.2f}")
            for r in results:
                eg = f"${r['estimated_gross']:,.2f}" if r["estimated_gross"] else "N/A"
                click.echo(
                    f"  {r['call_sign']} | {r['contract_number']} "
                    f"| {r['candidate'] or 'N/A'} | est_gross={eg}"
                )
        else:
            # Aggregate across all districts
            results = queries.summary_by_district(
                conn, candidate=candidate, state=state_filter,
            )
            if fmt == "json":
                rows = [
                    {
                        "district": r["district"],
                        "state": r["state"],
                        "estimated_gross": r["estimated_gross"],
                        "estimated_net": r["estimated_net"],
                        "total_spots": r["total_spots"],
                        "contract_count": r["contract_count"],
                        "dma_names": r["dma_names"],
                    }
                    for r in results
                ]
                click.echo(json_mod.dumps(rows, indent=2))
                return
            if not results:
                click.echo("No district-level ad exposure found.")
                return
            for r in results:
                eg = f"${r['estimated_gross']:,.2f}" if r["estimated_gross"] else "$0"
                en = f"${r['estimated_net']:,.2f}" if r["estimated_net"] else "$0"
                dmas = r["dma_names"] or "N/A"
                click.echo(
                    f"{r['district']} | estimated_gross={eg} estimated_net={en} "
                    f"| contracts={r['contract_count']} | DMAs: {dmas}"
                )
        return

    if group_by == "show":
        results = queries.summary_by_show(conn, candidate=candidate, station=station)
        if fmt == "json":
            rows = [
                {
                    "show_name": r["show_name"],
                    "total_line_items": r["total_line_items"],
                    "total_spots": r["total_spots"],
                    "total_spend": r["total_spend"],
                    "min_rate": r["min_rate"],
                    "max_rate": r["max_rate"],
                }
                for r in results
            ]
            click.echo(json_mod.dumps(rows, indent=2))
            return

        if not results:
            click.echo("No line items found.")
            return

        for r in results:
            spend = f"${r['total_spend']:,.2f}" if r["total_spend"] else "$0"
            click.echo(
                f"{r['show_name']} | spots={r['total_spots']} "
                f"| spend={spend} "
                f"| rate=${r['min_rate']:,.0f}-${r['max_rate']:,.0f}"
            )
    else:
        if candidate:
            results = queries.summary_by_candidate(conn, candidate)
        else:
            # Fall back to line_items query grouped by station
            results = queries.query_line_items(
                conn, station=station, show_name=show_name,
            )
            if fmt == "json":
                rows = [
                    {
                        "call_sign": r["call_sign"],
                        "show_name": r["show_name"],
                        "spots": r["spots"],
                        "rate_per_spot": r["rate_per_spot"],
                        "line_total": r["line_total"],
                    }
                    for r in results
                ]
                click.echo(json_mod.dumps(rows, indent=2))
                return

            if not results:
                click.echo("No line items found.")
                return

            for r in results:
                click.echo(
                    f"{r['call_sign']} | {r['show_name']} "
                    f"| spots={r['spots']} "
                    f"| rate=${r['rate_per_spot']:,.0f} "
                    f"| total=${r['line_total']:,.0f}"
                )
            return

        if fmt == "json":
            rows = [
                {
                    "call_sign": r["call_sign"],
                    "market": r["market"],
                    "total_spots": r["total_spots"],
                    "total_spend": r["total_spend"],
                }
                for r in results
            ]
            click.echo(json_mod.dumps(rows, indent=2))
            return

        if not results:
            click.echo("No line items found.")
            return

        for r in results:
            spend = f"${r['total_spend']:,.2f}" if r["total_spend"] else "$0"
            click.echo(
                f"{r['call_sign']} ({r['market']}) "
                f"| spots={r['total_spots']} | spend={spend}"
            )


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


DEFAULT_CROSSWALK = Path("data/downballot-cd-to-dma-2024.csv")


@cli.command("load-districts")
@click.option("--input", "input_path", type=click.Path(exists=True),
              default=str(DEFAULT_CROSSWALK),
              help="Downballot CD-to-DMA crosswalk CSV")
@click.pass_context
def load_districts_cmd(ctx, input_path):
    """Load district-to-DMA crosswalk from The Downballot CSV."""
    from fcc_ad_tracker.districts import load_crosswalk_csv, auto_match_markets, insert_crosswalk

    conn = ctx.obj["conn"]
    rows = load_crosswalk_csv(input_path)
    matched, unmatched = auto_match_markets(conn, rows)
    count = insert_crosswalk(conn, rows, matched)

    click.echo(
        "District-to-DMA crosswalk data from The Downballot (thedownballot.com)"
    )
    click.echo(
        f"Loaded {count} district-DMA mappings. "
        f"Matched {len(matched)}/{len(matched) + len(unmatched)} DMAs to stations."
    )
    if unmatched:
        click.echo(f"{len(unmatched)} unmatched (no stations downloaded for those markets):")
        for name in unmatched[:10]:
            click.echo(f"  {name}")
        if len(unmatched) > 10:
            click.echo(f"  ... and {len(unmatched) - 10} more")


@cli.command("map-dma")
@click.argument("dma_name")
@click.argument("fcc_market")
@click.pass_context
def map_dma_cmd(ctx, dma_name, fcc_market):
    """Manually map a DMA name to an FCC market string.

    For FCC's abbreviated/misspelled DMA names that can't auto-match.
    Example: fcc-ad-tracker map-dma "Sacramento-Stockton-Modesto" "SACRAMNTO-STKTON-MODESTO"
    """
    from fcc_ad_tracker.districts import update_market_mapping

    conn = ctx.obj["conn"]
    updated = update_market_mapping(conn, dma_name, fcc_market)
    if updated:
        click.echo(f"Mapped '{dma_name}' -> '{fcc_market}' ({updated} rows updated)")
    else:
        click.echo(f"No rows found with dma_name='{dma_name}'. Check spelling.")
