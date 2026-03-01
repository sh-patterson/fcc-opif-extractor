import sqlite3

import pytest

from fcc_ca_ads.db.connection import get_connection, init_schema, get_schema_sql
from fcc_ca_ads.db.queries import (
    upsert_station,
    get_station,
    get_station_by_call_sign,
    list_stations,
    upsert_file,
    get_file,
    mark_downloaded,
    mark_ocr_done,
    insert_extraction,
    get_extractions_for_file,
    query_extractions,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def test_init_schema(db):
    tables = [
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "stations" in tables
    assert "files" in tables
    assert "extractions" in tables


def test_schema_is_idempotent(db):
    init_schema(db)
    tables = [
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "stations" in tables


def test_get_connection_creates_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    assert db_path.exists()
    conn.close()


def test_get_schema_sql_returns_string():
    sql = get_schema_sql()
    assert "CREATE TABLE" in sql
    assert "stations" in sql


def test_foreign_keys_enabled(db):
    result = db.execute("PRAGMA foreign_keys").fetchone()
    assert result[0] == 1


def test_upsert_and_get_station(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    station = get_station(db, "1")
    assert station["call_sign"] == "KABC-TV"


def test_upsert_station_updates(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_station(db, "1", "KABC-TV", "LA UPDATED", "LOS ANGELES", "CA", "Full Service")
    station = get_station(db, "1")
    assert station["market"] == "LA UPDATED"


def test_get_station_by_call_sign(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    station = get_station_by_call_sign(db, "KABC-TV")
    assert station["entity_id"] == "1"


def test_list_stations(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_station(db, "2", "KPIX-TV", "SAN FRANCISCO-OAK-SAN JOSE", "SF", "CA", "Full Service")
    assert len(list_stations(db)) == 2
    assert len(list_stations(db, market="LOS ANGELES")) == 1


def test_upsert_and_get_file(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    f = get_file(db, "f1")
    assert f["file_name"] == "order.pdf"


def test_mark_downloaded(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    mark_downloaded(db, "f1", sha256="abc123", local_path="/data/raw/test.pdf")
    f = get_file(db, "f1")
    assert f["sha256"] == "abc123"
    assert f["downloaded_at"] is not None


def test_mark_ocr_done(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    mark_ocr_done(db, "f1", ocr_needed=True)
    f = get_file(db, "f1")
    assert f["ocr_needed"] == 1
    assert f["ocr_done"] == 1


def test_insert_and_query_extraction(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    insert_extraction(
        db, file_id="f1", field_name="advertiser",
        field_value="ACME PAC", confidence="high", page_number=1,
    )
    insert_extraction(
        db, file_id="f1", field_name="total",
        field_value="$15,000", confidence="high", page_number=1,
    )
    results = get_extractions_for_file(db, "f1")
    assert len(results) == 2


def test_query_extractions_by_candidate(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    insert_extraction(
        db, file_id="f1", field_name="candidate",
        field_value="Jane Smith", confidence="high", page_number=1,
    )
    results = query_extractions(db, field_name="candidate", value_like="%Smith%")
    assert len(results) == 1
    assert results[0]["field_value"] == "Jane Smith"


def test_query_extractions_by_market(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    insert_extraction(
        db, file_id="f1", field_name="advertiser",
        field_value="ACME PAC", confidence="high",
    )
    results = query_extractions(db, market="LOS ANGELES")
    assert len(results) == 1
    results = query_extractions(db, market="BAKERSFIELD")
    assert len(results) == 0
