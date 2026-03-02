from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_station(
    conn: sqlite3.Connection,
    entity_id: str,
    call_sign: str,
    market: str,
    city: str,
    state: str,
    service_type: str,
) -> None:
    conn.execute(
        """
        INSERT INTO stations (entity_id, call_sign, market, city, state, service_type)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_id) DO UPDATE SET
            call_sign=excluded.call_sign, market=excluded.market,
            city=excluded.city, state=excluded.state,
            service_type=excluded.service_type
        """,
        (entity_id, call_sign, market, city, state, service_type),
    )
    conn.commit()


def get_station(conn: sqlite3.Connection, entity_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM stations WHERE entity_id = ?", (entity_id,)
    ).fetchone()


def get_station_by_call_sign(conn: sqlite3.Connection, call_sign: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM stations WHERE call_sign = ?", (call_sign,)
    ).fetchone()


def list_stations(conn: sqlite3.Connection, market: str | None = None) -> list[sqlite3.Row]:
    if market:
        return conn.execute("SELECT * FROM stations WHERE market = ?", (market,)).fetchall()
    return conn.execute("SELECT * FROM stations").fetchall()


def upsert_rss_item(
    conn: sqlite3.Connection,
    *,
    guid: str,
    entity_id: str | None,
    call_sign: str,
    title: str,
    link: str,
    published_at: str | None,
    raw_xml: str,
) -> bool:
    """Insert RSS item if new. Returns True when inserted, False when already present."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO rss_items (
            guid, entity_id, call_sign, title, link, published_at, seen_at, raw_xml
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (guid, entity_id, call_sign, title, link, published_at, _now(), raw_xml),
    )
    conn.commit()
    return cur.rowcount > 0


def list_rss_items(
    conn: sqlite3.Connection,
    *,
    call_sign: str | None = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    query = "SELECT * FROM rss_items WHERE 1=1"
    params: list = []
    if call_sign:
        query += " AND call_sign = ?"
        params.append(call_sign)
    query += " ORDER BY COALESCE(published_at, seen_at) DESC LIMIT ?"
    params.append(limit)
    return conn.execute(query, params).fetchall()


def upsert_nab_form(
    conn: sqlite3.Connection,
    *,
    file_id: str,
    entity_id: str | None,
    form_type: str | None,
    candidate_name: str | None,
    office_sought: str | None,
    party_affiliation: str | None,
    election_level: str | None,
    raw_text: str,
) -> None:
    conn.execute(
        """
        INSERT INTO nab_forms (
            file_id, entity_id, form_type, candidate_name, office_sought,
            party_affiliation, election_level, raw_text, extracted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            entity_id=excluded.entity_id,
            form_type=excluded.form_type,
            candidate_name=excluded.candidate_name,
            office_sought=excluded.office_sought,
            party_affiliation=excluded.party_affiliation,
            election_level=excluded.election_level,
            raw_text=excluded.raw_text,
            extracted_at=excluded.extracted_at
        """,
        (
            file_id,
            entity_id,
            form_type,
            candidate_name,
            office_sought,
            party_affiliation,
            election_level,
            raw_text,
            _now(),
        ),
    )
    conn.commit()


def query_nab_forms(
    conn: sqlite3.Connection,
    *,
    candidate: str | None = None,
    office_sought: str | None = None,
    station: str | None = None,
) -> list[sqlite3.Row]:
    query = """
        SELECT n.*, s.call_sign, s.market, f.file_name
        FROM nab_forms n
        LEFT JOIN stations s ON n.entity_id = s.entity_id
        LEFT JOIN files f ON n.file_id = f.file_id
        WHERE 1=1
    """
    params: list = []
    if candidate:
        query += " AND n.candidate_name LIKE ?"
        params.append(f"%{candidate}%")
    if office_sought:
        query += " AND n.office_sought LIKE ?"
        params.append(f"%{office_sought}%")
    if station:
        query += " AND s.call_sign = ?"
        params.append(station)
    query += " ORDER BY n.extracted_at DESC"
    return conn.execute(query, params).fetchall()


def upsert_candidate(
    conn: sqlite3.Connection,
    *,
    canonical_name: str,
    office_sought: str | None = None,
) -> int:
    now = _now()
    conn.execute(
        """
        INSERT INTO candidates (canonical_name, office_sought, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(canonical_name) DO UPDATE SET
            office_sought=COALESCE(excluded.office_sought, candidates.office_sought),
            updated_at=excluded.updated_at
        """,
        (canonical_name, office_sought, now, now),
    )
    row = conn.execute(
        "SELECT id FROM candidates WHERE canonical_name = ?",
        (canonical_name,),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def add_candidate_alias(conn: sqlite3.Connection, *, candidate_id: int, alias_name: str) -> None:
    conn.execute(
        """
        INSERT INTO candidate_aliases (candidate_id, alias_name, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(alias_name) DO UPDATE SET candidate_id=excluded.candidate_id
        """,
        (candidate_id, alias_name, _now()),
    )
    conn.commit()


def resolve_candidate_id(conn: sqlite3.Connection, name: str | None) -> int | None:
    if not name:
        return None
    row = conn.execute(
        """
        SELECT id
        FROM candidates
        WHERE LOWER(canonical_name) = LOWER(?)
        """,
        (name,),
    ).fetchone()
    if row:
        return int(row["id"])
    row = conn.execute(
        """
        SELECT candidate_id AS id
        FROM candidate_aliases
        WHERE LOWER(alias_name) = LOWER(?)
        """,
        (name,),
    ).fetchone()
    return int(row["id"]) if row else None


def link_contracts_to_candidate(
    conn: sqlite3.Connection,
    *,
    candidate_id: int,
    names: list[str],
) -> int:
    if not names:
        return 0
    cleaned = [n.strip() for n in names if n and n.strip()]
    if not cleaned:
        return 0
    params: list = [candidate_id, _now()]
    params.extend(cleaned)
    cur = conn.execute(
        f"""
        UPDATE contracts
        SET candidate_id = ?, updated_at = ?
        WHERE candidate_id IS NULL
          AND LOWER(candidate) IN ({",".join("LOWER(?)" for _ in cleaned)})
        """,
        params,
    )
    conn.commit()
    return cur.rowcount


def list_candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT c.id, c.canonical_name, c.office_sought,
               COUNT(DISTINCT ca.id) AS alias_count,
               COUNT(DISTINCT ct.contract_id) AS contract_count
        FROM candidates c
        LEFT JOIN candidate_aliases ca ON ca.candidate_id = c.id
        LEFT JOIN contracts ct ON ct.candidate_id = c.id
        GROUP BY c.id, c.canonical_name, c.office_sought
        ORDER BY c.canonical_name
        """
    ).fetchall()


def list_unlinked_contract_candidates(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT candidate, COUNT(*) AS contract_count
        FROM contracts
        WHERE candidate_id IS NULL
          AND candidate IS NOT NULL
          AND TRIM(candidate) != ''
        GROUP BY candidate
        ORDER BY contract_count DESC, candidate ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def list_candidate_aliases(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT ca.alias_name, ca.candidate_id, c.canonical_name
        FROM candidate_aliases ca
        JOIN candidates c ON ca.candidate_id = c.id
        ORDER BY c.canonical_name, ca.alias_name
        """
    ).fetchall()


def upsert_file(
    conn: sqlite3.Connection,
    *,
    file_id: str,
    entity_id: str,
    file_manager_id: str,
    file_name: str,
    folder_id: str,
    file_size: int,
    folder_path: str = "",
    create_ts: str | None = None,
    last_update_ts: str | None = None,
    history_status: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO files (file_id, entity_id, file_manager_id, file_name,
                           folder_id, folder_path, file_size,
                           create_ts, last_update_ts, history_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            file_name=excluded.file_name,
            file_size=excluded.file_size,
            folder_path=excluded.folder_path,
            create_ts=COALESCE(excluded.create_ts, files.create_ts),
            last_update_ts=COALESCE(excluded.last_update_ts, files.last_update_ts),
            history_status=COALESCE(excluded.history_status, files.history_status)
        """,
        (
            file_id, entity_id, file_manager_id, file_name,
            folder_id, folder_path, file_size,
            create_ts, last_update_ts, history_status,
        ),
    )
    conn.commit()


def get_file(conn: sqlite3.Connection, file_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone()


def mark_downloaded(conn: sqlite3.Connection, file_id: str, sha256: str, local_path: str) -> None:
    conn.execute(
        """
        UPDATE files
        SET sha256 = ?, local_path = ?, downloaded_at = ?, extraction_status = 'pending'
        WHERE file_id = ?
        """,
        (sha256, local_path, _now(), file_id),
    )
    conn.commit()


def mark_ocr_done(conn: sqlite3.Connection, file_id: str, ocr_needed: bool) -> None:
    conn.execute(
        "UPDATE files SET ocr_needed = ?, ocr_done = 1 WHERE file_id = ?",
        (int(ocr_needed), file_id),
    )
    conn.commit()


def set_extraction_status(conn: sqlite3.Connection, file_id: str, status: str) -> None:
    conn.execute(
        "UPDATE files SET extraction_status = ? WHERE file_id = ?",
        (status, file_id),
    )
    conn.commit()


def clear_extracted_data(conn: sqlite3.Connection, file_id: str) -> None:
    """Delete extracted rows for a file so it can be safely re-processed."""
    conn.execute("DELETE FROM extractions WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM line_items WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM line_item_weeks WHERE file_id = ?", (file_id,))
    conn.execute(
        """
        UPDATE contracts
        SET latest_file_id = NULL, updated_at = ?
        WHERE latest_file_id = ?
        """,
        (_now(), file_id),
    )
    conn.commit()


def prune_superseded_contract_line_items(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    contract_number: str,
    keep_file_id: str,
) -> None:
    """Keep line-items only for latest file revision of a contract within an entity."""
    conn.execute(
        """
        DELETE FROM line_items
        WHERE contract_number = ?
          AND file_id IN (
              SELECT file_id
              FROM files
              WHERE entity_id = ?
                AND file_id != ?
          )
        """,
        (contract_number, entity_id, keep_file_id),
    )
    conn.execute(
        """
        DELETE FROM line_item_weeks
        WHERE contract_number = ?
          AND file_id IN (
              SELECT file_id
              FROM files
              WHERE entity_id = ?
                AND file_id != ?
          )
        """,
        (contract_number, entity_id, keep_file_id),
    )
    conn.commit()


def file_exists_by_sha256(conn: sqlite3.Connection, sha256: str) -> sqlite3.Row | None:
    """Check if a file with this SHA-256 hash already exists."""
    return conn.execute(
        "SELECT * FROM files WHERE sha256 = ?", (sha256,)
    ).fetchone()


def set_file_type(conn: sqlite3.Connection, file_id: str, file_type: str) -> None:
    conn.execute(
        "UPDATE files SET file_type = ? WHERE file_id = ?",
        (file_type, file_id),
    )
    conn.commit()


def insert_extraction(
    conn: sqlite3.Connection,
    *,
    file_id: str,
    field_name: str,
    field_value: str,
    confidence: str,
    page_number: int = 0,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO extractions
            (file_id, field_name, field_value, confidence, page_number, extracted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (file_id, field_name, field_value, confidence, page_number, _now()),
    )
    conn.commit()


def get_extractions_for_file(conn: sqlite3.Connection, file_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM extractions WHERE file_id = ?", (file_id,)
    ).fetchall()


def upsert_contract(
    conn: sqlite3.Connection,
    *,
    contract_id: str,
    entity_id: str,
    contract_number: str,
    advertiser: str | None = None,
    candidate: str | None = None,
    candidate_id: int | None = None,
    office_sought: str | None = None,
    agency: str | None = None,
    contract_start: str | None = None,
    contract_end: str | None = None,
    total_spots: int | None = None,
    gross_total: float | None = None,
    agency_commission: float | None = None,
    net_total: float | None = None,
    demographic: str | None = None,
    extraction_method: str | None = None,
    revision_number: int = 0,
    latest_file_id: str | None = None,
) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO contracts (
            contract_id, entity_id, contract_number, advertiser, candidate,
            candidate_id, office_sought, agency, contract_start, contract_end, total_spots, gross_total,
            agency_commission, net_total, demographic, revision_number,
            extraction_method, latest_file_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(contract_id) DO UPDATE SET
            advertiser=excluded.advertiser, candidate=excluded.candidate,
            candidate_id=COALESCE(excluded.candidate_id, contracts.candidate_id),
            office_sought=COALESCE(excluded.office_sought, contracts.office_sought),
            agency=excluded.agency, contract_start=excluded.contract_start,
            contract_end=excluded.contract_end, total_spots=excluded.total_spots,
            gross_total=excluded.gross_total, agency_commission=excluded.agency_commission,
            net_total=excluded.net_total, demographic=excluded.demographic,
            revision_number=excluded.revision_number,
            extraction_method=COALESCE(excluded.extraction_method, contracts.extraction_method),
            latest_file_id=excluded.latest_file_id,
            updated_at=excluded.updated_at
        """,
        (
            contract_id, entity_id, contract_number, advertiser, candidate,
            candidate_id, office_sought, agency, contract_start, contract_end, total_spots, gross_total,
            agency_commission, net_total, demographic, revision_number,
            extraction_method, latest_file_id, now, now,
        ),
    )
    conn.commit()


def get_contract(conn: sqlite3.Connection, contract_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM contracts WHERE contract_id = ?", (contract_id,)
    ).fetchone()


def query_contracts(
    conn: sqlite3.Connection,
    *,
    candidate: str | None = None,
    advertiser: str | None = None,
    entity_id: str | None = None,
    market: str | None = None,
) -> list[sqlite3.Row]:
    query = """
        SELECT c.*, s.call_sign, s.market,
               COALESCE(cn.canonical_name, c.candidate) AS candidate_name
        FROM contracts c
        JOIN stations s ON c.entity_id = s.entity_id
        LEFT JOIN candidates cn ON c.candidate_id = cn.id
        WHERE 1=1
    """
    params: list = []
    if candidate:
        query += " AND COALESCE(cn.canonical_name, c.candidate) LIKE ?"
        params.append(f"%{candidate}%")
    if advertiser:
        query += " AND c.advertiser LIKE ?"
        params.append(f"%{advertiser}%")
    if entity_id:
        query += " AND c.entity_id = ?"
        params.append(entity_id)
    if market:
        query += " AND s.market = ?"
        params.append(market)
    query += " ORDER BY c.contract_start DESC"
    return conn.execute(query, params).fetchall()


def insert_line_item(
    conn: sqlite3.Connection,
    *,
    file_id: str,
    contract_number: str | None = None,
    line_number: int | None = None,
    channel: str | None = None,
    show_name: str | None = None,
    time_slot: str | None = None,
    spot_length: str | None = None,
    rate_type: str | None = None,
    spots: int | None = None,
    rate_per_spot: float | None = None,
    line_total: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page_number: int = 0,
    extraction_method: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO line_items (
            file_id, contract_number, line_number, channel, show_name,
            time_slot, spot_length, rate_type, spots, rate_per_spot,
            line_total, start_date, end_date, page_number, extracted_at, extraction_method
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id, contract_number, line_number, channel, show_name,
            time_slot, spot_length, rate_type, spots, rate_per_spot,
            line_total, start_date, end_date, page_number, _now(), extraction_method,
        ),
    )
    conn.commit()


def insert_line_item_week(
    conn: sqlite3.Connection,
    *,
    file_id: str,
    contract_number: str | None,
    page_number: int,
    start_date: str,
    end_date: str,
    day_pattern: str | None,
    spots: int | None,
    rate: float | None,
    extraction_method: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO line_item_weeks (
            file_id, contract_number, page_number, start_date, end_date,
            day_pattern, spots, rate, extracted_at, extraction_method
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            contract_number,
            page_number,
            start_date,
            end_date,
            day_pattern,
            spots,
            rate,
            _now(),
            extraction_method,
        ),
    )
    conn.commit()


def summary_by_week(
    conn: sqlite3.Connection,
    *,
    candidate: str | None = None,
    station: str | None = None,
) -> list[sqlite3.Row]:
    query = """
        WITH candidate_by_file AS (
            SELECT file_id, MAX(field_value) AS candidate
            FROM extractions
            WHERE field_name = 'candidate'
            GROUP BY file_id
        )
        SELECT liw.start_date, liw.end_date,
               SUM(liw.spots) AS total_spots,
               SUM(COALESCE(liw.spots, 0) * COALESCE(liw.rate, 0)) AS estimated_spend
        FROM line_item_weeks liw
        JOIN files f ON liw.file_id = f.file_id
        JOIN stations s ON f.entity_id = s.entity_id
        LEFT JOIN contracts c ON liw.contract_number = c.contract_number
            AND f.entity_id = c.entity_id
        LEFT JOIN candidates cn ON c.candidate_id = cn.id
        LEFT JOIN candidate_by_file cbf ON cbf.file_id = liw.file_id
        WHERE (
            liw.contract_number IS NULL
            OR c.latest_file_id IS NULL
            OR liw.file_id = c.latest_file_id
        )
    """
    params: list = []
    if candidate:
        query += " AND COALESCE(cn.canonical_name, c.candidate, cbf.candidate) LIKE ?"
        params.append(f"%{candidate}%")
    if station:
        query += " AND s.call_sign = ?"
        params.append(station)
    query += " GROUP BY liw.start_date, liw.end_date ORDER BY liw.start_date ASC"
    return conn.execute(query, params).fetchall()


def get_line_items_for_file(conn: sqlite3.Connection, file_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM line_items WHERE file_id = ?", (file_id,)
    ).fetchall()


def query_line_items(
    conn: sqlite3.Connection,
    *,
    candidate: str | None = None,
    station: str | None = None,
    show_name: str | None = None,
) -> list[sqlite3.Row]:
    """Query line items with optional filters via contracts and stations joins."""
    query = """
        WITH candidate_by_file AS (
            SELECT file_id, MAX(field_value) AS candidate
            FROM extractions
            WHERE field_name = 'candidate'
            GROUP BY file_id
        )
        SELECT li.*, f.file_name, f.entity_id, s.call_sign, s.market,
               c.advertiser,
               COALESCE(cn.canonical_name, c.candidate, cbf.candidate) AS candidate
        FROM line_items li
        JOIN files f ON li.file_id = f.file_id
        JOIN stations s ON f.entity_id = s.entity_id
        LEFT JOIN contracts c ON li.contract_number = c.contract_number
            AND f.entity_id = c.entity_id
        LEFT JOIN candidates cn ON c.candidate_id = cn.id
        LEFT JOIN candidate_by_file cbf ON cbf.file_id = li.file_id
        WHERE 1=1
    """
    params: list = []
    if candidate:
        query += " AND COALESCE(cn.canonical_name, c.candidate, cbf.candidate) LIKE ?"
        params.append(f"%{candidate}%")
    if station:
        query += " AND s.call_sign = ?"
        params.append(station)
    if show_name:
        query += " AND li.show_name LIKE ?"
        params.append(f"%{show_name}%")
    query += " ORDER BY li.rate_per_spot DESC"
    return conn.execute(query, params).fetchall()


def summary_by_candidate(
    conn: sqlite3.Connection,
    candidate: str,
) -> list[sqlite3.Row]:
    """Aggregate spend by station for a candidate."""
    return conn.execute(
        """
        WITH candidate_by_file AS (
            SELECT file_id, MAX(field_value) AS candidate
            FROM extractions
            WHERE field_name = 'candidate'
            GROUP BY file_id
        )
        SELECT s.call_sign, s.market,
               COUNT(*) as total_line_items,
               SUM(li.spots) as total_spots,
               SUM(li.line_total) as total_spend
        FROM line_items li
        JOIN files f ON li.file_id = f.file_id
        JOIN stations s ON f.entity_id = s.entity_id
        LEFT JOIN contracts c ON li.contract_number = c.contract_number
            AND f.entity_id = c.entity_id
        LEFT JOIN candidates cn ON c.candidate_id = cn.id
        LEFT JOIN candidate_by_file cbf ON cbf.file_id = li.file_id
        WHERE COALESCE(cn.canonical_name, c.candidate, cbf.candidate) LIKE ?
          AND (
              li.contract_number IS NULL
              OR c.latest_file_id IS NULL
              OR li.file_id = c.latest_file_id
          )
        GROUP BY s.call_sign, s.market
        ORDER BY total_spend DESC
        """,
        (f"%{candidate}%",),
    ).fetchall()


def summary_by_show(
    conn: sqlite3.Connection,
    *,
    candidate: str | None = None,
    station: str | None = None,
) -> list[sqlite3.Row]:
    """Aggregate spend by show name."""
    query = """
        WITH candidate_by_file AS (
            SELECT file_id, MAX(field_value) AS candidate
            FROM extractions
            WHERE field_name = 'candidate'
            GROUP BY file_id
        )
        SELECT li.show_name,
               COUNT(*) as total_line_items,
               SUM(li.spots) as total_spots,
               SUM(li.line_total) as total_spend,
               MIN(li.rate_per_spot) as min_rate,
               MAX(li.rate_per_spot) as max_rate
        FROM line_items li
        JOIN files f ON li.file_id = f.file_id
        JOIN stations s ON f.entity_id = s.entity_id
        LEFT JOIN contracts c ON li.contract_number = c.contract_number
            AND f.entity_id = c.entity_id
        LEFT JOIN candidates cn ON c.candidate_id = cn.id
        LEFT JOIN candidate_by_file cbf ON cbf.file_id = li.file_id
        WHERE (
            li.contract_number IS NULL
            OR c.latest_file_id IS NULL
            OR li.file_id = c.latest_file_id
        )
    """
    params: list = []
    if candidate:
        query += " AND COALESCE(cn.canonical_name, c.candidate, cbf.candidate) LIKE ?"
        params.append(f"%{candidate}%")
    if station:
        query += " AND s.call_sign = ?"
        params.append(station)
    query += " GROUP BY li.show_name ORDER BY total_spend DESC"
    return conn.execute(query, params).fetchall()


def query_contracts_by_district(
    conn: sqlite3.Connection,
    district: str,
    *,
    candidate: str | None = None,
    advertiser: str | None = None,
) -> list[sqlite3.Row]:
    """Return contracts touching a district, with weighted totals."""
    query = """
        SELECT dd.district, dd.state, dd.dma_name, dd.weight,
               c.contract_id, c.contract_number, c.advertiser,
               COALESCE(cn.canonical_name, c.candidate) AS candidate,
               c.agency, c.contract_start, c.contract_end, c.total_spots,
               c.gross_total, c.net_total,
               c.gross_total * dd.weight AS estimated_gross,
               c.net_total * dd.weight AS estimated_net,
               s.call_sign, s.market
        FROM contracts c
        JOIN stations s ON c.entity_id = s.entity_id
        LEFT JOIN candidates cn ON c.candidate_id = cn.id
        JOIN dma_districts dd ON dd.fcc_market = s.market
        WHERE dd.district = ?
    """
    params: list = [district]
    if candidate:
        query += " AND COALESCE(cn.canonical_name, c.candidate) LIKE ?"
        params.append(f"%{candidate}%")
    if advertiser:
        query += " AND c.advertiser LIKE ?"
        params.append(f"%{advertiser}%")
    query += " ORDER BY estimated_gross DESC"
    return conn.execute(query, params).fetchall()


def summary_by_district(
    conn: sqlite3.Connection,
    *,
    candidate: str | None = None,
    state: str | None = None,
) -> list[sqlite3.Row]:
    """Aggregate estimated ad exposure per district."""
    query = """
        SELECT dd.district, dd.state,
               SUM(c.gross_total * dd.weight) AS estimated_gross,
               SUM(c.net_total * dd.weight) AS estimated_net,
               SUM(c.total_spots) AS total_spots,
               COUNT(DISTINCT c.contract_id) AS contract_count,
               GROUP_CONCAT(DISTINCT dd.dma_name) AS dma_names
        FROM contracts c
        JOIN stations s ON c.entity_id = s.entity_id
        LEFT JOIN candidates cn ON c.candidate_id = cn.id
        JOIN dma_districts dd ON dd.fcc_market = s.market
        WHERE 1=1
    """
    params: list = []
    if candidate:
        query += " AND COALESCE(cn.canonical_name, c.candidate) LIKE ?"
        params.append(f"%{candidate}%")
    if state:
        query += " AND dd.state = ?"
        params.append(state)
    query += " GROUP BY dd.district, dd.state ORDER BY estimated_gross DESC"
    return conn.execute(query, params).fetchall()


def districts_for_market(conn: sqlite3.Connection, market: str) -> list[sqlite3.Row]:
    """List all districts touched by a DMA market."""
    return conn.execute(
        """
        SELECT district, state, dma_name, weight, population
        FROM dma_districts
        WHERE fcc_market = ?
        ORDER BY weight DESC
        """,
        (market,),
    ).fetchall()


def district_dma_weights(conn: sqlite3.Connection, district: str) -> list[sqlite3.Row]:
    """Get the DMA weight breakdown for a single district."""
    return conn.execute(
        """
        SELECT dma_name, fcc_market, weight, population
        FROM dma_districts
        WHERE district = ?
        ORDER BY weight DESC
        """,
        (district,),
    ).fetchall()


def query_extractions(
    conn: sqlite3.Connection,
    *,
    field_name: str | None = None,
    value_like: str | None = None,
    market: str | None = None,
    since: str | None = None,
) -> list[sqlite3.Row]:
    query = """
        SELECT e.*, f.file_name, f.entity_id, s.call_sign, s.market
        FROM extractions e
        JOIN files f ON e.file_id = f.file_id
        JOIN stations s ON f.entity_id = s.entity_id
        WHERE 1=1
    """
    params: list = []
    if field_name:
        query += " AND e.field_name = ?"
        params.append(field_name)
    if value_like:
        query += " AND e.field_value LIKE ?"
        params.append(value_like)
    if market:
        query += " AND s.market = ?"
        params.append(market)
    if since:
        query += " AND f.downloaded_at >= ?"
        params.append(since)
    return conn.execute(query, params).fetchall()
