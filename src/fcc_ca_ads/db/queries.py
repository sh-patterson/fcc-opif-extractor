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
) -> None:
    conn.execute(
        """
        INSERT INTO files (file_id, entity_id, file_manager_id, file_name,
                           folder_id, folder_path, file_size)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            file_name=excluded.file_name, file_size=excluded.file_size
        """,
        (file_id, entity_id, file_manager_id, file_name, folder_id, folder_path, file_size),
    )
    conn.commit()


def get_file(conn: sqlite3.Connection, file_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone()


def mark_downloaded(conn: sqlite3.Connection, file_id: str, sha256: str, local_path: str) -> None:
    conn.execute(
        "UPDATE files SET sha256 = ?, local_path = ?, downloaded_at = ? WHERE file_id = ?",
        (sha256, local_path, _now(), file_id),
    )
    conn.commit()


def mark_ocr_done(conn: sqlite3.Connection, file_id: str, ocr_needed: bool) -> None:
    conn.execute(
        "UPDATE files SET ocr_needed = ?, ocr_done = 1 WHERE file_id = ?",
        (int(ocr_needed), file_id),
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
        INSERT INTO extractions (file_id, field_name, field_value, confidence,
                                 page_number, extracted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (file_id, field_name, field_value, confidence, page_number, _now()),
    )
    conn.commit()


def get_extractions_for_file(conn: sqlite3.Connection, file_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM extractions WHERE file_id = ?", (file_id,)
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
