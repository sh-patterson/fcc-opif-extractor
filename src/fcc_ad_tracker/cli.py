import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from email.utils import parsedate_to_datetime
from difflib import SequenceMatcher

import click
from dotenv import load_dotenv

from fcc_ad_tracker.config import DEFAULT_TARGET_DMAS, OpifConfig
from fcc_ad_tracker.client import OpifClient
from fcc_ad_tracker.db.connection import get_connection
from fcc_ad_tracker.db import queries
from fcc_ad_tracker.discover import (
    Station,
    discover_stations,
    discover_stations_by_dmas,
    save_stations,
)
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
    load_dotenv(override=False)
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


def _station_fields_from_search_row(row: dict) -> tuple[str, str, str, str, str]:
    """Best-effort station metadata mapping from /search/api docs."""
    call_sign = (
        row.get("call_sign")
        or row.get("callSign")
        or row.get("facility_call_sign")
        or row.get("facilityCallSign")
        or row.get("licensee_call_sign")
        or row.get("licenseeCallSign")
        or row.get("callsign")
        or ""
    )
    market = (
        row.get("market")
        or row.get("nielsen_dma")
        or row.get("nielsenDma")
        or row.get("dma_name")
        or row.get("dmaName")
        or ""
    )
    community = row.get("community")
    community_city = community.get("city") if isinstance(community, dict) else ""
    community_state = community.get("state") if isinstance(community, dict) else ""
    city = (
        row.get("city")
        or row.get("community_city")
        or row.get("communityCity")
        or community_city
        or ""
    )
    state = (
        row.get("state")
        or row.get("community_state")
        or row.get("communityState")
        or community_state
        or ""
    )
    service_type = (
        row.get("service_type")
        or row.get("serviceType")
        or row.get("service")
        or row.get("source_service_code")
        or "Unknown"
    )
    return str(call_sign), str(market), str(city), str(state), str(service_type)


def _parse_rss_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


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
@click.option(
    "--cross-state-dma/--single-state-dma",
    default=False,
    help="Search all US states and keep stations in target DMAs (fixes cross-state DMA gaps).",
)
@click.pass_context
def discover(ctx, state, output, cross_state_dma):
    """Discover TV stations from FCC facility search."""
    conn = ctx.obj["conn"]
    client = _make_client(ctx)
    if cross_state_dma:
        stations = discover_stations_by_dmas(
            client,
            target_dmas=DEFAULT_TARGET_DMAS,
        )
    else:
        stations = discover_stations(client, state=state, target_dmas=DEFAULT_TARGET_DMAS)

    if not stations:
        click.echo(
            f"Warning: FCC facility search returned 0 stations for state {state}."
        )
        if not cross_state_dma:
            fallback_rows = queries.list_stations(conn)
            if fallback_rows:
                stations = [
                    Station(
                        entity_id=r["entity_id"],
                        call_sign=r["call_sign"],
                        market=r["market"] or "",
                        city=r["city"] or "",
                        state=r["state"] or "",
                        service_type=r["service_type"] or "",
                    )
                    for r in fallback_rows
                ]
                click.echo(
                    f"Using {len(stations)} stations already present in local DB as fallback. "
                    "Use --cross-state-dma to broaden discovery."
                )
            else:
                click.echo(
                    "No local fallback stations available. Try --cross-state-dma or seed stations manually."
                )
    save_stations(stations, Path(output))
    for s in stations:
        queries.upsert_station(
            conn, s.entity_id, s.call_sign, s.market, s.city, s.state, s.service_type
        )
    click.echo(f"Discovered {len(stations)} stations, saved to {output}")


@cli.command("search-api")
@click.option("--query", default="*", help="Search query string for FCC /search/api")
@click.option("--campaign-year", default=None, help="Campaign year filter (e.g. 2026)")
@click.option("--office-type", default=None, help="Office type filter")
@click.option("--political-file-type", default=None, help="Political file type filter")
@click.option("--limit", default=100, type=int, help="Max result docs to fetch")
@click.option("--ingest", is_flag=True, help="Ingest matched file metadata into local files table")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def search_api(ctx, query, campaign_year, office_type, political_file_type, limit, ingest, fmt):
    """Search FCC /search/api across entities."""
    conn = ctx.obj["conn"]
    client = _make_client(ctx)

    rows: list[dict] = []
    page = 0
    page_size = min(limit, 100)
    try:
        while len(rows) < limit:
            batch = client.search_political_files(
                query=query,
                campaign_year=campaign_year,
                office_type=office_type,
                political_file_type=political_file_type,
                page=page,
                size=min(page_size, limit - len(rows)),
            )
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < min(page_size, limit - (len(rows) - len(batch))):
                break
            page += 1
    except Exception as exc:
        click.echo(f"search-api request failed: {exc}")
        return

    rows = rows[:limit]
    ingested = 0
    if ingest:
        for r in rows:
            file_id = r.get("file_id") or r.get("id")
            entity_id = (
                r.get("entity_id")
                or r.get("entityId")
                or r.get("facility_id")
                or r.get("facilityId")
            )
            if not file_id or not entity_id:
                continue
            existing_station = queries.get_station(conn, str(entity_id))
            call_sign, market, city, state, service_type = _station_fields_from_search_row(r)
            queries.upsert_station(
                conn,
                str(entity_id),
                call_sign or (existing_station["call_sign"] if existing_station else f"ENTITY-{entity_id}"),
                market or (existing_station["market"] if existing_station else ""),
                city or (existing_station["city"] if existing_station else ""),
                state or (existing_station["state"] if existing_station else ""),
                service_type or (existing_station["service_type"] if existing_station else "Unknown"),
            )
            queries.upsert_file(
                conn,
                file_id=str(file_id),
                entity_id=str(entity_id),
                file_manager_id=str(r.get("file_manager_id") or r.get("fileManagerId") or ""),
                file_name=str(r.get("file_name") or r.get("fileName") or "unknown"),
                folder_id=str(r.get("folder_id") or r.get("folderId") or ""),
                file_size=int(r.get("file_size") or r.get("fileSize") or 0),
                folder_path=str(r.get("file_folder_path") or r.get("fileFolderPath") or ""),
                create_ts=r.get("create_ts") or r.get("createTs"),
                last_update_ts=r.get("last_update_ts") or r.get("lastUpdateTs"),
                history_status=r.get("history_status") or r.get("historyStatus"),
            )
            ingested += 1

    if fmt == "json":
        import json
        click.echo(json.dumps(rows, indent=2))
    else:
        click.echo(f"Found {len(rows)} results from /search/api")
        for r in rows[:20]:
            file_name = r.get("file_name") or r.get("fileName") or "unknown"
            file_id = r.get("file_id") or r.get("id") or "n/a"
            entity_id = r.get("entity_id") or r.get("entityId") or r.get("facility_id") or "n/a"
            click.echo(f"{entity_id} | {file_id} | {file_name}")
    if ingest:
        click.echo(f"Ingested {ingested} file metadata rows")


@cli.command("rss-poll")
@click.option("--station", help="Single station call sign")
@click.option("--all", "all_stations", is_flag=True, help="Poll RSS for all stations in DB")
@click.option("--limit", default=50, type=int, help="Max RSS items to read per station")
@click.pass_context
def rss_poll(ctx, station, all_stations, limit):
    """Poll station RSS feeds and ingest newly seen items."""
    from fcc_ad_tracker.rss import parse_rss_items

    conn = ctx.obj["conn"]
    client = _make_client(ctx)

    if station:
        s = queries.get_station_by_call_sign(conn, station)
        if not s:
            click.echo(f"Station {station} not found in database. Run 'discover' first.")
            return
        stations = [s]
    elif all_stations:
        stations = queries.list_stations(conn)
    else:
        click.echo("Specify --station or --all")
        return

    total_seen = 0
    total_new = 0
    for s in stations:
        call_sign = s["call_sign"]
        try:
            xml_text = client.get_station_rss(call_sign)
            items = parse_rss_items(xml_text)[:limit]
        except Exception as exc:
            logger.error("RSS poll failed for %s: %s", call_sign, exc)
            continue

        new_count = 0
        for item in items:
            inserted = queries.upsert_rss_item(
                conn,
                guid=item.guid,
                entity_id=s["entity_id"],
                call_sign=call_sign,
                title=item.title,
                link=item.link,
                published_at=item.published_at,
                raw_xml=item.raw_xml,
            )
            if inserted:
                new_count += 1
        total_seen += len(items)
        total_new += new_count
        click.echo(f"{call_sign}: {new_count} new of {len(items)} feed items")

    click.echo(
        f"RSS polling complete: {total_new} new items across {len(stations)} stations "
        f"({total_seen} items examined)"
    )


@cli.command("rss-sync")
@click.option("--station", help="Single station call sign")
@click.option("--all", "all_stations", is_flag=True, help="Sync RSS for all stations in DB")
@click.option("--limit", default=50, type=int, help="Max RSS items to read per station")
@click.option("--lookback-days", default=30, type=int,
              help="Fallback history window (days) when RSS dates are missing")
@click.option("--max-files", default=200, type=int, help="Max files to download per station")
@click.option("--workers", default=1, type=int, help="Download worker threads per station")
@click.option("--run-extract/--no-run-extract", default=True,
              help="Run extract after RSS-triggered downloads")
@click.option("--use-gemini/--no-gemini", default=None,
              help="Passed through to extract when --run-extract is enabled")
@click.pass_context
def rss_sync(
    ctx, station, all_stations, limit, lookback_days, max_files, workers, run_extract, use_gemini
):
    """Poll RSS, download likely-new files, then extract."""
    from fcc_ad_tracker.rss import parse_rss_items
    from datetime import date

    db_path = ctx.obj["db_path"]
    conn = ctx.obj["conn"]
    client = _make_client(ctx)
    scratchpad = ctx.obj.get("scratchpad")

    if station:
        s = queries.get_station_by_call_sign(conn, station)
        if not s:
            click.echo(f"Station {station} not found in database. Run 'discover' first.")
            return
        stations = [s]
    elif all_stations:
        stations = queries.list_stations(conn)
    else:
        click.echo("Specify --station or --all")
        return

    today = date.today().isoformat()
    fallback_since = (datetime.now() - timedelta(days=lookback_days)).date().isoformat()
    total_new = 0
    total_downloaded = 0
    for s in stations:
        call_sign = s["call_sign"]
        entity_id = s["entity_id"]
        try:
            xml_text = client.get_station_rss(call_sign)
            items = parse_rss_items(xml_text)[:limit]
        except Exception as exc:
            logger.error("RSS sync failed for %s: %s", call_sign, exc)
            continue

        station_new = 0
        min_new_dt: datetime | None = None
        for item in items:
            inserted = queries.upsert_rss_item(
                conn,
                guid=item.guid,
                entity_id=entity_id,
                call_sign=call_sign,
                title=item.title,
                link=item.link,
                published_at=item.published_at,
                raw_xml=item.raw_xml,
            )
            if inserted:
                station_new += 1
                dt = _parse_rss_pub_date(item.published_at)
                if dt and (min_new_dt is None or dt < min_new_dt):
                    min_new_dt = dt

        total_new += station_new
        if station_new == 0:
            click.echo(f"{call_sign}: no new RSS items")
            continue

        since = min_new_dt.date().isoformat() if min_new_dt else fallback_since
        downloaded = _download_station(
            client,
            db_path,
            entity_id,
            call_sign,
            since,
            today,
            max_files,
            dry_run=False,
            workers=workers,
            scratchpad=scratchpad,
        )
        total_downloaded += downloaded
        click.echo(
            f"{call_sign}: {station_new} new RSS items, downloaded {downloaded} files "
            f"(since {since})"
        )

    click.echo(
        f"RSS sync complete: {total_new} new RSS items, {total_downloaded} files downloaded"
    )
    if run_extract and total_downloaded > 0:
        ctx.invoke(extract, use_gemini=use_gemini, reextract=False)


@cli.command("rss-list")
@click.option("--station", help="Filter by station call sign")
@click.option("--limit", default=50, type=int, help="Max rows to display")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def rss_list(ctx, station, limit, fmt):
    """List ingested RSS feed items."""
    import json

    conn = ctx.obj["conn"]
    rows = queries.list_rss_items(conn, call_sign=station, limit=limit)
    if fmt == "json":
        click.echo(json.dumps([dict(r) for r in rows], indent=2))
        return
    if not rows:
        click.echo("No RSS items found.")
        return
    for r in rows:
        click.echo(
            f"{r['call_sign'] or 'N/A'} | {r['published_at'] or r['seen_at']} "
            f"| {r['title'] or 'N/A'}"
        )


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

    # Use paged file history API — prevents truncation on busy stations.
    history = []
    offset = 0
    page_size = min(max_files, 100)
    while len(history) < max_files:
        batch_count = min(page_size, max_files - len(history))
        batch = client.get_file_history(
            entity_id,
            since,
            until,
            count=batch_count,
            offset=offset,
        )
        if not batch:
            break
        history.extend(batch)
        if len(batch) < batch_count:
            break
        offset += len(batch)

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
            "create_ts": h.get("create_ts"),
            "last_update_ts": h.get("last_update_ts"),
            "history_status": h.get("history_status"),
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
                create_ts=item.get("create_ts"),
                last_update_ts=item.get("last_update_ts"),
                history_status=item.get("history_status"),
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
                create_ts=item.get("create_ts"),
                last_update_ts=item.get("last_update_ts"),
                history_status=item.get("history_status"),
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
@click.option("--use-gemini/--no-gemini", default=None,
              help="Use Gemini Flash for extraction fallback (default: auto-detect)")
@click.option("--reextract", is_flag=True,
              help="Re-process files already extracted (clears prior per-file extraction rows).")
@click.pass_context
def extract(ctx, use_gemini, reextract):
    """Extract fields from downloaded PDFs."""
    from fcc_ad_tracker.extract import extract_pdf_text
    from fcc_ad_tracker.fields import extract_all_fields, FieldMatch, CONFIDENCE_ORDER
    from fcc_ad_tracker.contracts import extract_contract_meta
    from fcc_ad_tracker.line_items import (
        parse_line_items,
        parse_week_breakdowns,
        count_line_item_candidates,
    )
    from fcc_ad_tracker.nab_extract import extract_nab_form
    from fcc_ad_tracker.classify import classify_file_type, is_terms_and_conditions

    conn = ctx.obj["conn"]
    scratchpad = ctx.obj.get("scratchpad")

    # Resolve Gemini availability
    if use_gemini is None:
        use_gemini = bool(os.environ.get("GOOGLE_API_KEY"))

    if reextract:
        files = conn.execute(
            """
            SELECT f.* FROM files f
            WHERE f.downloaded_at IS NOT NULL
            ORDER BY f.downloaded_at ASC
            """
        ).fetchall()
    else:
        files = conn.execute(
            """
            SELECT f.* FROM files f
            WHERE f.downloaded_at IS NOT NULL
              AND COALESCE(f.extraction_status, 'pending') IN ('pending', 'error')
            ORDER BY f.downloaded_at ASC
            """
        ).fetchall()
    count = 0
    with click.progressbar(files, label="Extracting", show_pos=True) as bar:
        for f in bar:
            path = Path(f["local_path"]) if f["local_path"] else None
            if not path or not path.exists():
                queries.set_extraction_status(conn, f["file_id"], "error")
                continue
            if reextract:
                queries.clear_extracted_data(conn, f["file_id"])
            queries.set_extraction_status(conn, f["file_id"], "processing")
            try:
                result = extract_pdf_text(path)
            except Exception as exc:
                logger.error("Failed to extract %s (%s): %s", f["file_id"], path, exc)
                queries.set_extraction_status(conn, f["file_id"], "error")
                if scratchpad:
                    scratchpad.log(
                        "error",
                        operation="extract",
                        error_message=str(exc),
                        file_id=f["file_id"],
                        local_path=str(path),
                    )
                continue

            # Content-based file type classification (refine from filename-based)
            effective_file_type = f["file_type"] or "unknown"
            if result.pages:
                content_type = classify_file_type(
                    f["file_name"], f["folder_path"] or "",
                    page0_text=result.pages[0],
                )
                if content_type != "unknown":
                    queries.set_file_type(conn, f["file_id"], content_type)
                    effective_file_type = content_type

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
            nab_data = extract_nab_form(full_text)
            if nab_data:
                queries.upsert_nab_form(
                    conn,
                    file_id=f["file_id"],
                    entity_id=f["entity_id"],
                    form_type=nab_data.form_type,
                    candidate_name=nab_data.candidate_name,
                    office_sought=nab_data.office_sought,
                    party_affiliation=nab_data.party_affiliation,
                    election_level=nab_data.election_level,
                    raw_text=full_text[:4000],
                )
                if nab_data.candidate_name:
                    queries.insert_extraction(
                        conn,
                        file_id=f["file_id"],
                        field_name="candidate",
                        field_value=nab_data.candidate_name,
                        confidence="high",
                        page_number=0,
                    )
                if nab_data.office_sought:
                    queries.insert_extraction(
                        conn,
                        file_id=f["file_id"],
                        field_name="office_sought",
                        field_value=nab_data.office_sought,
                        confidence="high",
                        page_number=0,
                    )
            meta = extract_contract_meta(full_text)
            if meta.contract_number:
                entity_id = f["entity_id"]
                contract_id = f"{entity_id}:{meta.contract_number}"

                # Get advertiser/candidate from field extraction if contract doesn't have them
                advertiser = best.get("advertiser")
                candidate = best.get("candidate")
                office_sought = best.get("office_sought")
                candidate_id = queries.resolve_candidate_id(
                    conn,
                    candidate.value if candidate else None,
                )
                if candidate and candidate_id is None:
                    candidate_id = queries.upsert_candidate(
                        conn,
                        canonical_name=candidate.value,
                        office_sought=office_sought.value if office_sought else None,
                    )
                    queries.add_candidate_alias(
                        conn, candidate_id=candidate_id, alias_name=candidate.value
                    )

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
                        candidate_id=candidate_id,
                        office_sought=office_sought.value if office_sought else None,
                        agency=meta.agency,
                        contract_start=meta.contract_start,
                        contract_end=meta.contract_end,
                        total_spots=meta.total_spots,
                        gross_total=meta.gross_total,
                        agency_commission=meta.agency_commission,
                        net_total=meta.net_total,
                        demographic=meta.demographic,
                        extraction_method="regex",
                        revision_number=meta.revision_number,
                        latest_file_id=f["file_id"],
                    )
                    queries.prune_superseded_contract_line_items(
                        conn,
                        entity_id=entity_id,
                        contract_number=meta.contract_number,
                        keep_file_id=f["file_id"],
                    )

            # Line-item extraction across all pages (skip T&C pages)
            contract_num = meta.contract_number if meta.contract_number else None
            regex_line_count = 0
            attempted_line_count = 0
            for page_num, page_text in enumerate(result.pages):
                if is_terms_and_conditions(page_text):
                    continue
                attempted_line_count += count_line_item_candidates(page_text)
                page_items = parse_line_items(page_text)
                regex_line_count += len(page_items)
                week_items = parse_week_breakdowns(page_text)
                for wk in week_items:
                    queries.insert_line_item_week(
                        conn,
                        file_id=f["file_id"],
                        contract_number=contract_num,
                        page_number=page_num,
                        start_date=wk["start_date"],
                        end_date=wk["end_date"],
                        day_pattern=wk.get("day_pattern"),
                        spots=wk.get("spots"),
                        rate=wk.get("rate"),
                        extraction_method="regex",
                    )
                for li in page_items:
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
                        extraction_method="regex",
                    )

            # Gemini fallback when regex missed contract number or line items
            gemini_line_count = 0
            extraction_method = "regex"
            if use_gemini and (meta.contract_number is None or regex_line_count == 0):
                from fcc_ad_tracker.gemini_extract import (
                    gemini_extract as _gemini_extract,
                    gemini_result_to_contract_meta,
                    gemini_result_to_line_items,
                )

                non_tc_pages = [
                    p for p in result.pages
                    if not is_terms_and_conditions(p)
                ]
                gemini_result = _gemini_extract(non_tc_pages)
                if gemini_result:
                    extraction_method = "gemini"

                    # Fill contract meta gaps
                    if meta.contract_number is None:
                        gmeta = gemini_result_to_contract_meta(gemini_result)
                        if gmeta.contract_number:
                            meta.contract_number = gmeta.contract_number
                        if meta.agency is None:
                            meta.agency = gmeta.agency
                        if meta.demographic is None:
                            meta.demographic = gmeta.demographic
                        if meta.contract_start is None:
                            meta.contract_start = gmeta.contract_start
                        if meta.contract_end is None:
                            meta.contract_end = gmeta.contract_end

                        # Upsert contract with Gemini-recovered data
                        if meta.contract_number:
                            entity_id = f["entity_id"]
                            contract_id = f"{entity_id}:{meta.contract_number}"
                            advertiser = best.get("advertiser")
                            candidate = best.get("candidate")
                            office_sought = best.get("office_sought")
                            candidate_id = queries.resolve_candidate_id(
                                conn,
                                candidate.value if candidate else gemini_result.contract.candidate,
                            )
                            if candidate_id is None:
                                cname = (
                                    candidate.value if candidate
                                    else gemini_result.contract.candidate
                                )
                                if cname:
                                    candidate_id = queries.upsert_candidate(
                                        conn,
                                        canonical_name=cname,
                                        office_sought=office_sought.value if office_sought else None,
                                    )
                                    queries.add_candidate_alias(
                                        conn, candidate_id=candidate_id, alias_name=cname
                                    )
                            queries.upsert_contract(
                                conn,
                                contract_id=contract_id,
                                entity_id=entity_id,
                                contract_number=meta.contract_number,
                                advertiser=(
                                    advertiser.value if advertiser
                                    else gemini_result.contract.advertiser
                                ),
                                candidate=(
                                    candidate.value if candidate
                                    else gemini_result.contract.candidate
                                ),
                                candidate_id=candidate_id,
                                office_sought=office_sought.value if office_sought else None,
                                agency=meta.agency,
                                contract_start=meta.contract_start,
                                contract_end=meta.contract_end,
                                total_spots=meta.total_spots,
                                gross_total=meta.gross_total,
                                agency_commission=meta.agency_commission,
                                net_total=meta.net_total,
                                demographic=meta.demographic,
                                extraction_method="gemini",
                                revision_number=meta.revision_number,
                                latest_file_id=f["file_id"],
                            )
                            queries.prune_superseded_contract_line_items(
                                conn,
                                entity_id=entity_id,
                                contract_number=meta.contract_number,
                                keep_file_id=f["file_id"],
                            )
                            contract_num = meta.contract_number

                    # Fill line item gaps
                    if regex_line_count == 0:
                        gemini_items = gemini_result_to_line_items(gemini_result)
                        gemini_line_count = len(gemini_items)
                        for li in gemini_items:
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
                                page_number=0,
                                extraction_method="gemini",
                            )

            if attempted_line_count and regex_line_count < attempted_line_count:
                logger.warning(
                    "Partial line-item extraction for %s: matched %d/%d candidate lines",
                    f["file_id"],
                    regex_line_count,
                    attempted_line_count,
                )
                if scratchpad:
                    scratchpad.log(
                        "line_item_near_miss",
                        file_id=f["file_id"],
                        matched=regex_line_count,
                        attempted=attempted_line_count,
                    )

            queries.mark_ocr_done(conn, f["file_id"], ocr_needed=result.ocr_used)
            total_line_items = regex_line_count + gemini_line_count
            if total_line_items > 0:
                final_status = "done"
            elif nab_data or effective_file_type in {"nab", "traffic", "invoice"}:
                final_status = "not_applicable"
            else:
                final_status = "no_line_items"
            queries.set_extraction_status(conn, f["file_id"], final_status)
            if scratchpad:
                scratchpad.log(
                    "extraction",
                    file_id=f["file_id"],
                    fields_found=list(best.keys()),
                    contract_number=contract_num,
                    line_items_count=regex_line_count + gemini_line_count,
                    extraction_method=extraction_method,
                    extraction_status=final_status,
                )
            count += 1
    click.echo(f"Extracted fields from {count} files")


_CONTRACT_COLUMNS = [
    "call_sign", "market", "contract_number", "advertiser", "candidate_name",
    "office_sought", "agency", "contract_start", "contract_end", "total_spots",
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
        candidate_name = r["candidate_name"] if "candidate_name" in r.keys() else r["candidate"]
        click.echo(
            f"{r['call_sign']} | {r['contract_number']} "
            f"| {r['advertiser'] or 'N/A'} "
            f"| {candidate_name or 'N/A'} "
            f"| office={r['office_sought'] or 'N/A'} "
            f"| gross={gross} net={net} spots={spots}"
        )


@cli.command()
@click.option("--candidate", help="Filter by candidate name")
@click.option("--station", help="Filter by station call sign")
@click.option("--show", "show_name", help="Filter by show name")
@click.option("--district", help="Filter by congressional district (e.g. CA-27)")
@click.option("--state", "state_filter", help="Filter by state (e.g. CA, TX)")
@click.option("--by", "group_by", type=click.Choice(["station", "show", "district", "week"]),
              default="station", help="Group results by station, show, district, or week")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def summary(ctx, candidate, station, show_name, district, state_filter, group_by, fmt):
    """Summarize ad spend by station, show, district, or week."""
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
            min_r = f"${r['min_rate']:,.0f}" if r["min_rate"] else "N/A"
            max_r = f"${r['max_rate']:,.0f}" if r["max_rate"] else "N/A"
            click.echo(
                f"{r['show_name']} | spots={r['total_spots']} "
                f"| spend={spend} "
                f"| rate={min_r}-{max_r}"
            )
    elif group_by == "week":
        results = queries.summary_by_week(conn, candidate=candidate, station=station)
        if fmt == "json":
            rows = [
                {
                    "start_date": r["start_date"],
                    "end_date": r["end_date"],
                    "total_spots": r["total_spots"],
                    "estimated_spend": r["estimated_spend"],
                }
                for r in results
            ]
            click.echo(json_mod.dumps(rows, indent=2))
            return

        if not results:
            click.echo("No weekly breakdowns found.")
            return

        for r in results:
            est = f"${r['estimated_spend']:,.2f}" if r["estimated_spend"] else "$0"
            click.echo(
                f"{r['start_date']} - {r['end_date']} "
                f"| spots={r['total_spots'] or 0} | est_spend={est}"
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
                rate = f"${r['rate_per_spot']:,.0f}" if r['rate_per_spot'] else "N/A"
                total = f"${r['line_total']:,.0f}" if r['line_total'] else "N/A"
                click.echo(
                    f"{r['call_sign']} | {r['show_name']} "
                    f"| spots={r['spots']} "
                    f"| rate={rate} "
                    f"| total={total}"
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


@cli.command("nab")
@click.option("--candidate", help="Filter by candidate name")
@click.option("--office", "office_sought", help="Filter by office sought")
@click.option("--station", help="Filter by station call sign")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def nab_cmd(ctx, candidate, office_sought, station, fmt):
    """List extracted NAB PB-18/PB-19 form metadata."""
    import json

    conn = ctx.obj["conn"]
    rows = queries.query_nab_forms(
        conn,
        candidate=candidate,
        office_sought=office_sought,
        station=station,
    )
    if fmt == "json":
        click.echo(json.dumps([dict(r) for r in rows], indent=2))
        return
    if not rows:
        click.echo("No NAB forms found.")
        return
    for r in rows:
        click.echo(
            f"{r['call_sign'] or 'N/A'} | {r['form_type'] or 'NAB'} "
            f"| {r['candidate_name'] or 'N/A'} "
            f"| office={r['office_sought'] or 'N/A'} "
            f"| party={r['party_affiliation'] or 'N/A'} "
            f"| level={r['election_level'] or 'N/A'}"
        )


@cli.command("normalize-candidate")
@click.option("--canonical", required=True, help="Canonical candidate name")
@click.option("--alias", "aliases", multiple=True, help="Alias variant (repeatable)")
@click.option("--office", "office_sought", default=None, help="Office sought")
@click.pass_context
def normalize_candidate_cmd(ctx, canonical, aliases, office_sought):
    """Create/update canonical candidate and map aliases to it."""
    conn = ctx.obj["conn"]
    candidate_id = queries.upsert_candidate(
        conn,
        canonical_name=canonical,
        office_sought=office_sought,
    )
    queries.add_candidate_alias(conn, candidate_id=candidate_id, alias_name=canonical)
    for alias in aliases:
        queries.add_candidate_alias(conn, candidate_id=candidate_id, alias_name=alias)
    linked = queries.link_contracts_to_candidate(
        conn,
        candidate_id=candidate_id,
        names=[canonical, *aliases],
    )
    click.echo(
        f"Candidate #{candidate_id}: canonical='{canonical}', "
        f"aliases={1 + len(aliases)}, linked_contracts={linked}"
    )


@cli.command("list-candidates")
@click.pass_context
def list_candidates_cmd(ctx):
    """List normalized candidates and linkage counts."""
    conn = ctx.obj["conn"]
    rows = queries.list_candidates(conn)
    if not rows:
        click.echo("No normalized candidates.")
        return
    for r in rows:
        click.echo(
            f"{r['id']}: {r['canonical_name']} "
            f"| office={r['office_sought'] or 'N/A'} "
            f"| aliases={r['alias_count']} contracts={r['contract_count']}"
        )


@cli.command("suggest-candidate-links")
@click.option("--limit", default=100, type=int, help="Max unresolved candidate variants")
@click.option("--min-score", default=85, type=int, help="Minimum fuzzy score (0-100)")
@click.option("--apply", "apply_changes", is_flag=True,
              help="Apply suggestions (create aliases + link contracts)")
@click.pass_context
def suggest_candidate_links_cmd(ctx, limit, min_score, apply_changes):
    """Suggest normalized candidate links for unlinked contract candidate names."""
    conn = ctx.obj["conn"]
    unresolved = queries.list_unlinked_contract_candidates(conn, limit=limit)
    if not unresolved:
        click.echo("No unresolved candidate names.")
        return

    candidates = queries.list_candidates(conn)
    aliases = queries.list_candidate_aliases(conn)
    exact_map: dict[str, tuple[int, str, str]] = {}
    for c in candidates:
        exact_map[c["canonical_name"].strip().lower()] = (c["id"], c["canonical_name"], "canonical")
    for a in aliases:
        exact_map[a["alias_name"].strip().lower()] = (
            a["candidate_id"], a["canonical_name"], "alias",
        )

    candidate_names = [(c["id"], c["canonical_name"]) for c in candidates]
    suggestions: list[dict] = []
    for row in unresolved:
        raw = row["candidate"]
        key = raw.strip().lower()
        if key in exact_map:
            cid, cname, match_type = exact_map[key]
            suggestions.append(
                {
                    "raw": raw,
                    "count": row["contract_count"],
                    "candidate_id": cid,
                    "canonical_name": cname,
                    "score": 100,
                    "match_type": f"exact_{match_type}",
                }
            )
            continue

        best_id = None
        best_name = None
        best_score = 0
        for cid, cname in candidate_names:
            cname_key = cname.strip().lower()
            if cname_key in key or key in cname_key:
                score = 95
            else:
                score = int(SequenceMatcher(None, key, cname_key).ratio() * 100)
            if score > best_score:
                best_score = score
                best_id = cid
                best_name = cname
        if best_id is not None and best_score >= min_score:
            suggestions.append(
                {
                    "raw": raw,
                    "count": row["contract_count"],
                    "candidate_id": best_id,
                    "canonical_name": best_name,
                    "score": best_score,
                    "match_type": "fuzzy",
                }
            )

    if not suggestions:
        click.echo("No candidate link suggestions met the threshold.")
        return

    applied_aliases = 0
    applied_links = 0
    for s in suggestions:
        click.echo(
            f"{s['raw']} -> {s['canonical_name']} "
            f"(score={s['score']}, type={s['match_type']}, contracts={s['count']})"
        )
        if apply_changes:
            queries.add_candidate_alias(
                conn, candidate_id=s["candidate_id"], alias_name=s["raw"]
            )
            applied_aliases += 1
            applied_links += queries.link_contracts_to_candidate(
                conn, candidate_id=s["candidate_id"], names=[s["raw"]]
            )

    if apply_changes:
        click.echo(
            f"Applied {applied_aliases} aliases, linked {applied_links} contracts"
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
