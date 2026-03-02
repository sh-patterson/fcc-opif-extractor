import sqlite3

import pytest

from fcc_ad_tracker.db.connection import get_connection, init_schema, get_schema_sql
from fcc_ad_tracker.db.queries import (
    upsert_station,
    get_station,
    get_station_by_call_sign,
    list_stations,
    upsert_file,
    get_file,
    mark_downloaded,
    mark_ocr_done,
    set_extraction_status,
    clear_extracted_data,
    insert_extraction,
    get_extractions_for_file,
    query_extractions,
    upsert_contract,
    get_contract,
    query_contracts,
    insert_line_item,
    get_line_items_for_file,
    query_line_items,
    summary_by_candidate,
    summary_by_show,
    summary_by_week,
    upsert_candidate,
    add_candidate_alias,
    resolve_candidate_id,
    link_contracts_to_candidate,
    list_candidates,
    upsert_rss_item,
    list_rss_items,
    upsert_nab_form,
    query_nab_forms,
    prune_superseded_contract_line_items,
    file_exists_by_sha256,
    set_file_type,
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


def test_candidate_normalization_workflow(db):
    candidate_id = upsert_candidate(db, canonical_name="Tom Steyer", office_sought="GOVERNOR")
    add_candidate_alias(db, candidate_id=candidate_id, alias_name="TOM STEYER FOR GOVERNOR 2026")
    assert resolve_candidate_id(db, "Tom Steyer") == candidate_id
    assert resolve_candidate_id(db, "TOM STEYER FOR GOVERNOR 2026") == candidate_id
    rows = list_candidates(db)
    assert len(rows) == 1
    assert rows[0]["canonical_name"] == "Tom Steyer"


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


def test_set_extraction_status(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    set_extraction_status(db, "f1", "done")
    f = get_file(db, "f1")
    assert f["extraction_status"] == "done"


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


def test_insert_extraction_is_idempotent(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    insert_extraction(
        db, file_id="f1", field_name="candidate",
        field_value="Jane Smith", confidence="high", page_number=1,
    )
    insert_extraction(
        db, file_id="f1", field_name="candidate",
        field_value="Jane Smith", confidence="high", page_number=1,
    )
    assert len(get_extractions_for_file(db, "f1")) == 1


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


def test_contracts_table_exists(db):
    tables = [
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "contracts" in tables


def test_upsert_and_get_contract(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    upsert_contract(
        db,
        contract_id="1:424082",
        entity_id="1",
        contract_number="424082",
        advertiser="TOM STEYER FOR GOVERNOR 2026",
        candidate="Tom Steyer",
        office_sought="GOVERNOR",
        agency="BUYER'S EDGE MEDIA LLC",
        contract_start="02/23/2026",
        contract_end="03/09/2026",
        total_spots=227,
        gross_total=522700.00,
        agency_commission=78405.00,
        net_total=444295.00,
        demographic="A25-54",
        revision_number=0,
        latest_file_id="f1",
    )
    c = get_contract(db, "1:424082")
    assert c is not None
    assert c["contract_number"] == "424082"
    assert c["advertiser"] == "TOM STEYER FOR GOVERNOR 2026"
    assert c["gross_total"] == 522700.00
    assert c["net_total"] == 444295.00
    assert c["total_spots"] == 227
    assert c["office_sought"] == "GOVERNOR"


def test_upsert_contract_updates_revision(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    upsert_file(
        db, file_id="f2", entity_id="1", file_manager_id="fm-2",
        file_name="order-rev1.pdf", folder_id="fold-1", file_size=1024,
    )
    upsert_contract(
        db, contract_id="1:424082", entity_id="1", contract_number="424082",
        gross_total=500000.00, revision_number=0, latest_file_id="f1",
    )
    upsert_contract(
        db, contract_id="1:424082", entity_id="1", contract_number="424082",
        gross_total=522700.00, revision_number=1, latest_file_id="f2",
    )
    c = get_contract(db, "1:424082")
    assert c["gross_total"] == 522700.00
    assert c["revision_number"] == 1
    assert c["latest_file_id"] == "f2"


def test_query_contracts_by_candidate(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_contract(
        db, contract_id="1:100", entity_id="1", contract_number="100",
        candidate="Tom Steyer",
    )
    upsert_contract(
        db, contract_id="1:200", entity_id="1", contract_number="200",
        candidate="Jane Smith",
    )
    results = query_contracts(db, candidate="Steyer")
    assert len(results) == 1
    assert results[0]["candidate"] == "Tom Steyer"


def test_query_contracts_uses_canonical_candidate_name(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_contract(
        db, contract_id="1:100", entity_id="1", contract_number="100",
        candidate="TOM STEYER FOR GOVERNOR 2026",
    )
    cid = upsert_candidate(db, canonical_name="Tom Steyer")
    add_candidate_alias(db, candidate_id=cid, alias_name="TOM STEYER FOR GOVERNOR 2026")
    linked = link_contracts_to_candidate(
        db, candidate_id=cid, names=["TOM STEYER FOR GOVERNOR 2026"]
    )
    assert linked == 1
    results = query_contracts(db, candidate="Tom Steyer")
    assert len(results) == 1
    assert results[0]["candidate_name"] == "Tom Steyer"


def test_query_contracts_by_market(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_station(db, "2", "KPIX-TV", "SAN FRANCISCO", "SF", "CA", "Full Service")
    upsert_contract(
        db, contract_id="1:100", entity_id="1", contract_number="100",
        candidate="Tom Steyer",
    )
    upsert_contract(
        db, contract_id="2:200", entity_id="2", contract_number="200",
        candidate="Tom Steyer",
    )
    results = query_contracts(db, market="LOS ANGELES")
    assert len(results) == 1
    assert results[0]["call_sign"] == "KABC-TV"


def test_line_items_table_exists(db):
    tables = [
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "line_items" in tables
    assert "line_item_weeks" in tables
    assert "rss_items" in tables
    assert "nab_forms" in tables


def test_upsert_rss_item(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    inserted = upsert_rss_item(
        db,
        guid="guid-1",
        entity_id="1",
        call_sign="KABC-TV",
        title="New Filing",
        link="https://publicfiles.fcc.gov/documents/1",
        published_at="Mon, 01 Mar 2026 12:00:00 GMT",
        raw_xml="<item/>",
    )
    assert inserted is True
    inserted2 = upsert_rss_item(
        db,
        guid="guid-1",
        entity_id="1",
        call_sign="KABC-TV",
        title="New Filing",
        link="https://publicfiles.fcc.gov/documents/1",
        published_at="Mon, 01 Mar 2026 12:00:00 GMT",
        raw_xml="<item/>",
    )
    assert inserted2 is False
    rows = list_rss_items(db, call_sign="KABC-TV", limit=10)
    assert len(rows) == 1


def test_upsert_and_query_nab_forms(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="nab.pdf", folder_id="fold-1", file_size=1000,
    )
    upsert_nab_form(
        db,
        file_id="f1",
        entity_id="1",
        form_type="PB-18",
        candidate_name="Tom Steyer",
        office_sought="Governor",
        party_affiliation="Democratic",
        election_level="state",
        raw_text="NAB FORM PB-18 ...",
    )
    rows = query_nab_forms(db, candidate="Steyer")
    assert len(rows) == 1
    assert rows[0]["form_type"] == "PB-18"
    assert rows[0]["office_sought"] == "Governor"


def _seed_line_items(db):
    """Helper to seed station, file, contract, and line items."""
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    upsert_contract(
        db, contract_id="1:424082", entity_id="1", contract_number="424082",
        candidate="Tom Steyer", advertiser="TOM STEYER FOR GOVERNOR",
    )
    insert_line_item(
        db, file_id="f1", contract_number="424082", line_number=58,
        channel="KABC", show_name="NBA LA Lakers", time_slot="various",
        spot_length=":30", rate_type="NM", spots=1, rate_per_spot=25000.0,
        line_total=25000.0, start_date="03/03/26", end_date="03/08/26",
    )
    insert_line_item(
        db, file_id="f1", contract_number="424082", line_number=59,
        channel="KABC", show_name="5A News", time_slot="5:00A-5:30A",
        spot_length=":30", rate_type="NM", spots=5, rate_per_spot=500.0,
        line_total=2500.0, start_date="03/03/26", end_date="03/07/26",
    )


def test_insert_and_get_line_items(db):
    _seed_line_items(db)
    items = get_line_items_for_file(db, "f1")
    assert len(items) == 2
    assert items[0]["show_name"] == "NBA LA Lakers"
    assert items[0]["rate_per_spot"] == 25000.0


def test_insert_line_item_is_idempotent(db):
    _seed_line_items(db)
    insert_line_item(
        db, file_id="f1", contract_number="424082", line_number=58,
        channel="KABC", show_name="NBA LA Lakers", time_slot="various",
        spot_length=":30", rate_type="NM", spots=1, rate_per_spot=25000.0,
        line_total=25000.0, start_date="03/03/26", end_date="03/08/26",
    )
    items = get_line_items_for_file(db, "f1")
    assert len(items) == 2


def test_query_line_items_by_candidate(db):
    _seed_line_items(db)
    items = query_line_items(db, candidate="Steyer")
    assert len(items) == 2
    # Should be ordered by rate_per_spot DESC
    assert items[0]["rate_per_spot"] == 25000.0


def test_query_line_items_by_show(db):
    _seed_line_items(db)
    items = query_line_items(db, show_name="Lakers")
    assert len(items) == 1
    assert items[0]["show_name"] == "NBA LA Lakers"


def test_query_line_items_candidate_falls_back_to_extractions(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    insert_extraction(
        db, file_id="f1", field_name="candidate",
        field_value="Tom Steyer", confidence="high", page_number=0,
    )
    insert_line_item(
        db, file_id="f1", contract_number=None, line_number=1,
        channel="KABC", show_name="Morning News", time_slot="5A-6A",
        spot_length=":30", rate_type="NM", spots=2, rate_per_spot=500.0,
        line_total=1000.0, start_date="03/03/26", end_date="03/07/26",
    )
    items = query_line_items(db, candidate="Steyer")
    assert len(items) == 1
    assert items[0]["candidate"] == "Tom Steyer"


def test_summary_by_candidate(db):
    _seed_line_items(db)
    summary = summary_by_candidate(db, "Steyer")
    assert len(summary) == 1
    assert summary[0]["call_sign"] == "KABC-TV"
    assert summary[0]["total_spots"] == 6
    assert summary[0]["total_spend"] == 27500.0


def test_summary_by_show(db):
    _seed_line_items(db)
    shows = summary_by_show(db, candidate="Steyer")
    assert len(shows) == 2
    # Ordered by total_spend DESC
    assert shows[0]["show_name"] == "NBA LA Lakers"
    assert shows[0]["total_spend"] == 25000.0


def test_summary_ignores_superseded_contract_revisions(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order-r0.pdf", folder_id="fold-1", file_size=1024,
    )
    upsert_file(
        db, file_id="f2", entity_id="1", file_manager_id="fm-2",
        file_name="order-r1.pdf", folder_id="fold-1", file_size=1024,
    )
    upsert_contract(
        db, contract_id="1:424082", entity_id="1", contract_number="424082",
        candidate="Tom Steyer", revision_number=1, latest_file_id="f2",
    )
    insert_line_item(
        db, file_id="f1", contract_number="424082", line_number=1,
        channel="KABC", show_name="Morning News", time_slot="5A-6A",
        spot_length=":30", rate_type="NM", spots=5, rate_per_spot=1000.0,
        line_total=5000.0, start_date="03/03/26", end_date="03/07/26",
    )
    insert_line_item(
        db, file_id="f2", contract_number="424082", line_number=1,
        channel="KABC", show_name="Morning News", time_slot="5A-6A",
        spot_length=":30", rate_type="NM", spots=2, rate_per_spot=1000.0,
        line_total=2000.0, start_date="03/03/26", end_date="03/07/26",
    )

    candidate_summary = summary_by_candidate(db, "Steyer")
    assert len(candidate_summary) == 1
    assert candidate_summary[0]["total_spend"] == 2000.0

    show_summary = summary_by_show(db, candidate="Steyer")
    assert len(show_summary) == 1
    assert show_summary[0]["total_spend"] == 2000.0


def test_prune_superseded_contract_line_items(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order-r0.pdf", folder_id="fold-1", file_size=1024,
    )
    upsert_file(
        db, file_id="f2", entity_id="1", file_manager_id="fm-2",
        file_name="order-r1.pdf", folder_id="fold-1", file_size=1024,
    )
    insert_line_item(
        db, file_id="f1", contract_number="424082", line_number=1,
        channel="KABC", show_name="Morning News", time_slot="5A-6A",
        spot_length=":30", rate_type="NM", spots=5, rate_per_spot=1000.0,
        line_total=5000.0, start_date="03/03/26", end_date="03/07/26",
    )
    insert_line_item(
        db, file_id="f2", contract_number="424082", line_number=1,
        channel="KABC", show_name="Morning News", time_slot="5A-6A",
        spot_length=":30", rate_type="NM", spots=2, rate_per_spot=1000.0,
        line_total=2000.0, start_date="03/03/26", end_date="03/07/26",
    )
    prune_superseded_contract_line_items(
        db, entity_id="1", contract_number="424082", keep_file_id="f2"
    )
    old_items = get_line_items_for_file(db, "f1")
    new_items = get_line_items_for_file(db, "f2")
    assert len(old_items) == 0
    assert len(new_items) == 1


def test_file_exists_by_sha256(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    mark_downloaded(db, "f1", sha256="abc123", local_path="/data/raw/test.pdf")
    assert file_exists_by_sha256(db, "abc123") is not None
    assert file_exists_by_sha256(db, "nonexistent") is None


def test_set_file_type(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    set_file_type(db, "f1", "contract")
    f = get_file(db, "f1")
    assert f["file_type"] == "contract"


def test_schema_migration_adds_file_type_column(tmp_path):
    """If DB was created before file_type was added, migration should add it."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    # Create files table WITHOUT file_type (simulates old schema)
    conn.execute("""
        CREATE TABLE stations (
            entity_id TEXT PRIMARY KEY,
            call_sign TEXT NOT NULL,
            market TEXT,
            city TEXT,
            state TEXT,
            service_type TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE files (
            file_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL REFERENCES stations(entity_id),
            file_manager_id TEXT,
            file_name TEXT,
            folder_id TEXT,
            folder_path TEXT,
            file_size INTEGER,
            sha256 TEXT,
            downloaded_at TEXT,
            local_path TEXT,
            ocr_needed INTEGER DEFAULT 0,
            ocr_done INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE contracts (
            contract_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL REFERENCES stations(entity_id),
            contract_number TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE line_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT NOT NULL REFERENCES files(file_id),
            contract_number TEXT,
            line_number INTEGER,
            channel TEXT,
            show_name TEXT,
            time_slot TEXT,
            spot_length TEXT,
            rate_type TEXT,
            spots INTEGER,
            rate_per_spot REAL,
            line_total REAL,
            start_date TEXT,
            end_date TEXT,
            page_number INTEGER,
            extracted_at TEXT
        )
    """)
    conn.commit()
    # Verify file_type is absent
    cols = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
    assert "file_type" not in cols
    conn.close()

    # Re-open via get_connection — migration should add the column
    conn = get_connection(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
    assert "file_type" in cols
    assert "extraction_status" in cols
    assert "create_ts" in cols
    assert "last_update_ts" in cols
    assert "history_status" in cols
    contract_cols = {r[1] for r in conn.execute("PRAGMA table_info(contracts)")}
    assert "candidate_id" in contract_cols
    assert "office_sought" in contract_cols
    assert "extraction_method" in contract_cols
    line_item_cols = {r[1] for r in conn.execute("PRAGMA table_info(line_items)")}
    assert "extraction_method" in line_item_cols
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "candidates" in tables
    assert "candidate_aliases" in tables
    assert "nab_forms" in tables

    # Verify set_file_type works on migrated DB
    conn.execute(
        "INSERT INTO stations VALUES ('1','KABC-TV','LA','LA','CA','Full Service')"
    )
    conn.execute(
        "INSERT INTO files (file_id, entity_id, file_name) VALUES ('f1','1','test.pdf')"
    )
    conn.commit()
    set_file_type(conn, "f1", "contract")
    f = conn.execute("SELECT file_type FROM files WHERE file_id='f1'").fetchone()
    assert f[0] == "contract"
    conn.close()


def test_clear_extracted_data(db):
    _seed_line_items(db)
    insert_extraction(
        db, file_id="f1", field_name="candidate",
        field_value="Tom Steyer", confidence="high", page_number=0,
    )
    clear_extracted_data(db, "f1")
    assert get_extractions_for_file(db, "f1") == []
    assert get_line_items_for_file(db, "f1") == []


def test_summary_by_week(db):
    upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service")
    upsert_file(
        db, file_id="f1", entity_id="1", file_manager_id="fm-1",
        file_name="order.pdf", folder_id="fold-1", file_size=1024,
    )
    upsert_contract(
        db, contract_id="1:424082", entity_id="1", contract_number="424082",
        candidate="Tom Steyer", latest_file_id="f1",
    )
    insert_extraction(
        db, file_id="f1", field_name="candidate",
        field_value="Tom Steyer", confidence="high", page_number=0,
    )
    from fcc_ad_tracker.db import queries as q
    q.insert_line_item_week(
        db,
        file_id="f1",
        contract_number="424082",
        page_number=0,
        start_date="03/03/26",
        end_date="03/08/26",
        day_pattern="-1111--",
        spots=5,
        rate=500.0,
        extraction_method="regex",
    )
    rows = summary_by_week(db, candidate="Steyer")
    assert len(rows) == 1
    assert rows[0]["total_spots"] == 5
    assert rows[0]["estimated_spend"] == 2500.0


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
