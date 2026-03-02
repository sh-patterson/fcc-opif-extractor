from unittest.mock import patch

import pytest
from click.testing import CliRunner

from fcc_ad_tracker.cli import cli
from fcc_ad_tracker.discover import Station


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "FCC Political Ad Tracker" in result.output


def test_status_command(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "status"])
    assert result.exit_code == 0
    assert "Stations: 0" in result.output


@patch("fcc_ad_tracker.cli.discover_stations")
@patch("fcc_ad_tracker.cli.save_stations")
def test_discover_command(mock_save, mock_discover, runner, tmp_path):
    mock_discover.return_value = [
        Station("1", "KABC-TV", "LOS ANGELES", "LOS ANGELES", "CA", "Full Service"),
    ]
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "discover"])
    assert result.exit_code == 0
    assert "Discovered 1 stations" in result.output
    mock_discover.assert_called_once()


def test_download_help_has_workers(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "download", "--help"])
    assert result.exit_code == 0
    assert "--workers" in result.output


def _seed_station(db_path, call_sign="KABC-TV", entity_id="E001"):
    """Seed a station into the database."""
    from fcc_ad_tracker.db.connection import get_connection
    from fcc_ad_tracker.db import queries as q

    conn = get_connection(db_path)
    q.upsert_station(conn, entity_id, call_sign, "LOS ANGELES", "LA", "CA", "Full Service")
    conn.close()


def _fake_history(n=3):
    """Generate n fake file history entries in political folders."""
    return [
        {
            "file_id": f"F{i:03d}",
            "file_name": f"ad-{i}.pdf",
            "file_manager_id": f"FM{i:03d}",
            "folder_id": f"FD{i:03d}",
            "file_size": 1000 + i,
            "file_folder_path": "/Political Files/2025",
        }
        for i in range(n)
    ]


@patch("fcc_ad_tracker.download.download_pdf")
def test_download_station_serial(mock_dl, runner, tmp_path):
    """_download_station with workers=1 downloads files and records them in DB."""
    from fcc_ad_tracker.cli import _download_station
    from fcc_ad_tracker.db.connection import get_connection
    from fcc_ad_tracker.db import queries as q
    from unittest.mock import MagicMock, patch as _patch

    db_path = str(tmp_path / "test.db")
    _seed_station(db_path)

    client = MagicMock()
    client.get_file_history.return_value = _fake_history(3)

    # Each file gets a unique hash so dedup doesn't trigger
    call_count = {"n": 0}
    def _unique_sha(_path):
        call_count["n"] += 1
        return f"sha-{call_count['n']}"

    with _patch("fcc_ad_tracker.download.sha256_file", side_effect=_unique_sha):
        count = _download_station(
            client, db_path, "E001", "KABC-TV", "2025-01-01", "2025-12-31", 100,
            dry_run=False, workers=1,
        )

    assert count == 3
    assert mock_dl.call_count == 3

    conn = get_connection(db_path)
    for i in range(3):
        f = q.get_file(conn, f"F{i:03d}")
        assert f is not None
        assert f["sha256"] is not None


@patch("fcc_ad_tracker.download.download_pdf")
def test_download_station_concurrent(mock_dl, runner, tmp_path):
    """_download_station with workers=2 downloads files concurrently and records all in DB."""
    from fcc_ad_tracker.cli import _download_station
    from fcc_ad_tracker.db.connection import get_connection
    from fcc_ad_tracker.db import queries as q
    from unittest.mock import MagicMock, patch as _patch
    import threading

    db_path = str(tmp_path / "test.db")
    _seed_station(db_path)

    client = MagicMock()
    client.get_file_history.return_value = _fake_history(4)

    # Thread-safe unique hash generator
    lock = threading.Lock()
    call_count = {"n": 0}
    def _unique_sha(_path):
        with lock:
            call_count["n"] += 1
            return f"sha-{call_count['n']}"

    with _patch("fcc_ad_tracker.download.sha256_file", side_effect=_unique_sha):
        count = _download_station(
            client, db_path, "E001", "KABC-TV", "2025-01-01", "2025-12-31", 100,
            dry_run=False, workers=2,
        )

    assert count == 4
    assert mock_dl.call_count == 4

    conn = get_connection(db_path)
    for i in range(4):
        f = q.get_file(conn, f"F{i:03d}")
        assert f is not None
        assert f["sha256"] is not None


@patch("fcc_ad_tracker.download.download_pdf")
def test_download_sha256_dedup(mock_dl, runner, tmp_path):
    """Files with identical SHA-256 hashes are skipped (dedup)."""
    from fcc_ad_tracker.cli import _download_station
    from unittest.mock import MagicMock, patch as _patch

    db_path = str(tmp_path / "test.db")
    _seed_station(db_path)

    client = MagicMock()
    client.get_file_history.return_value = _fake_history(3)

    # All files return same hash — only first should be kept
    with _patch("fcc_ad_tracker.download.sha256_file", return_value="same-hash"):
        count = _download_station(
            client, db_path, "E001", "KABC-TV", "2025-01-01", "2025-12-31", 100,
            dry_run=False, workers=1,
        )

    assert count == 1  # Only first file kept, rest deduped


def test_download_no_station(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "download"])
    assert result.exit_code == 0
    assert "Specify --station or --all" in result.output


def test_download_station_not_found(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "download", "--station", "WXYZ"])
    assert result.exit_code == 0
    assert "not found" in result.output


def test_extract_command(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "extract"])
    assert result.exit_code == 0
    assert "Extracted fields from 0 files" in result.output


def test_query_no_results(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "query", "--candidate", "Nobody"])
    assert result.exit_code == 0
    assert "No results found" in result.output


def _seed_extraction(db_path):
    """Seed a station, file, and extraction into the database for query tests."""
    from fcc_ad_tracker.db.connection import get_connection
    from fcc_ad_tracker.db import queries

    conn = get_connection(db_path)
    queries.upsert_station(conn, "E001", "KABC-TV", "LOS ANGELES", "LA", "CA", "Full Service")
    queries.upsert_file(
        conn,
        file_id="F001",
        entity_id="E001",
        file_manager_id="FM001",
        file_name="test-ad.pdf",
        folder_id="FD001",
        file_size=1234,
        folder_path="/Political Files/2025",
    )
    queries.mark_downloaded(conn, "F001", sha256="abc123", local_path="/tmp/test.pdf")
    queries.insert_extraction(
        conn,
        file_id="F001",
        field_name="candidate",
        field_value="Jane Smith",
        confidence="high",
        page_number=1,
    )
    conn.close()


def test_query_format_csv(runner, tmp_path):
    import csv
    import io

    db_path = tmp_path / "test.db"
    _seed_extraction(db_path)
    result = runner.invoke(cli, ["--db", str(db_path), "query", "--format", "csv"])
    assert result.exit_code == 0
    reader = csv.DictReader(io.StringIO(result.output))
    rows = list(reader)
    assert len(rows) == 1
    row = rows[0]
    assert row["call_sign"] == "KABC-TV"
    assert row["market"] == "LOS ANGELES"
    assert row["file_name"] == "test-ad.pdf"
    assert row["field_name"] == "candidate"
    assert row["field_value"] == "Jane Smith"
    assert row["confidence"] == "high"
    assert row["page_number"] == "1"


def test_query_format_json(runner, tmp_path):
    import json

    db_path = tmp_path / "test.db"
    _seed_extraction(db_path)
    result = runner.invoke(cli, ["--db", str(db_path), "query", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1
    rec = data[0]
    assert rec["call_sign"] == "KABC-TV"
    assert rec["field_value"] == "Jane Smith"
    assert rec["page_number"] == 1


def test_query_format_table_default(runner, tmp_path):
    """Default format (table) still works as before."""
    db_path = tmp_path / "test.db"
    _seed_extraction(db_path)
    result = runner.invoke(cli, ["--db", str(db_path), "query"])
    assert result.exit_code == 0
    assert "KABC-TV" in result.output
    assert "Jane Smith" in result.output


def test_query_format_csv_no_results(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "query", "--format", "csv"])
    assert result.exit_code == 0
    assert "No results found" in result.output


def test_contracts_command_no_results(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "contracts"])
    assert result.exit_code == 0
    assert "No contracts found" in result.output


def _seed_contract(db_path):
    """Seed a station and contract into the database for contract query tests."""
    from fcc_ad_tracker.db.connection import get_connection
    from fcc_ad_tracker.db import queries

    conn = get_connection(db_path)
    queries.upsert_station(conn, "E001", "KABC-TV", "LOS ANGELES", "LA", "CA", "Full Service")
    queries.upsert_file(
        conn,
        file_id="F001",
        entity_id="E001",
        file_manager_id="FM001",
        file_name="steyer-order.pdf",
        folder_id="FD001",
        file_size=1234,
        folder_path="/Political Files/2025",
    )
    queries.upsert_contract(
        conn,
        contract_id="E001:424082",
        entity_id="E001",
        contract_number="424082",
        advertiser="TOM STEYER FOR GOVERNOR 2026",
        candidate="Tom Steyer",
        agency="BUYER'S EDGE MEDIA LLC",
        contract_start="02/23/2026",
        contract_end="03/09/2026",
        total_spots=227,
        gross_total=522700.00,
        agency_commission=78405.00,
        net_total=444295.00,
        latest_file_id="F001",
    )
    conn.close()


def test_contracts_command_table(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_contract(db_path)
    result = runner.invoke(cli, ["--db", str(db_path), "contracts"])
    assert result.exit_code == 0
    assert "KABC-TV" in result.output
    assert "424082" in result.output
    assert "Tom Steyer" in result.output


def test_contracts_command_json(runner, tmp_path):
    import json

    db_path = tmp_path / "test.db"
    _seed_contract(db_path)
    result = runner.invoke(cli, ["--db", str(db_path), "contracts", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["contract_number"] == "424082"
    assert data[0]["gross_total"] == 522700.00


def test_contracts_command_csv(runner, tmp_path):
    import csv
    import io

    db_path = tmp_path / "test.db"
    _seed_contract(db_path)
    result = runner.invoke(cli, ["--db", str(db_path), "contracts", "--format", "csv"])
    assert result.exit_code == 0
    reader = csv.DictReader(io.StringIO(result.output))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["contract_number"] == "424082"


def test_contracts_command_filter_candidate(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_contract(db_path)
    result = runner.invoke(cli, ["--db", str(db_path), "contracts", "--candidate", "Steyer"])
    assert result.exit_code == 0
    assert "Tom Steyer" in result.output

    result = runner.invoke(cli, ["--db", str(db_path), "contracts", "--candidate", "Nobody"])
    assert result.exit_code == 0
    assert "No contracts found" in result.output


def test_extract_deduplicates_across_pages(runner, tmp_path):
    """Extract should produce one extraction per field per document, not per page."""
    from fpdf import FPDF
    from fcc_ad_tracker.db.connection import get_connection
    from fcc_ad_tracker.db import queries

    # Create a 3-page PDF where every page has the same advertiser
    pdf = FPDF()
    for _ in range(3):
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(text="Advertiser: ACME PAC")
        pdf.ln()
        pdf.cell(text="Candidate: Jane Smith")
        pdf.ln()
        pdf.cell(text="Total: $15,000.00")
    pdf_path = tmp_path / "multi.pdf"
    pdf.output(str(pdf_path))

    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    queries.upsert_station(conn, "E001", "KABC-TV", "LOS ANGELES", "LA", "CA", "Full Service")
    queries.upsert_file(
        conn,
        file_id="F001",
        entity_id="E001",
        file_manager_id="FM001",
        file_name="multi.pdf",
        folder_id="FD001",
        file_size=1234,
        folder_path="/Political Files/2025",
    )
    queries.mark_downloaded(conn, "F001", sha256="abc", local_path=str(pdf_path))
    conn.close()

    result = runner.invoke(cli, ["--db", str(db_path), "extract"])
    assert result.exit_code == 0

    conn = get_connection(db_path)
    extractions = queries.get_extractions_for_file(conn, "F001")
    field_names = [e["field_name"] for e in extractions]
    # Should have at most one extraction per field
    assert len(field_names) == len(set(field_names))


def _seed_line_items(db_path):
    """Seed station, file, contract, and line items for summary tests."""
    from fcc_ad_tracker.db.connection import get_connection
    from fcc_ad_tracker.db import queries

    conn = get_connection(db_path)
    queries.upsert_station(conn, "E001", "KABC-TV", "LOS ANGELES", "LA", "CA", "Full Service")
    queries.upsert_file(
        conn, file_id="F001", entity_id="E001", file_manager_id="FM001",
        file_name="order.pdf", folder_id="FD001", file_size=1234,
        folder_path="/Political Files/2025",
    )
    queries.upsert_contract(
        conn, contract_id="E001:424082", entity_id="E001", contract_number="424082",
        candidate="Tom Steyer", advertiser="TOM STEYER FOR GOVERNOR",
    )
    queries.insert_line_item(
        conn, file_id="F001", contract_number="424082", line_number=58,
        channel="KABC", show_name="NBA LA Lakers", time_slot="various",
        spot_length=":30", rate_type="NM", spots=1, rate_per_spot=25000.0,
        line_total=25000.0, start_date="03/03/26", end_date="03/08/26",
    )
    queries.insert_line_item(
        conn, file_id="F001", contract_number="424082", line_number=59,
        channel="KABC", show_name="5A News", time_slot="5:00A-5:30A",
        spot_length=":30", rate_type="NM", spots=5, rate_per_spot=500.0,
        line_total=2500.0, start_date="03/03/26", end_date="03/07/26",
    )
    conn.close()


def test_summary_command_no_results(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "summary", "--candidate", "Nobody"])
    assert result.exit_code == 0
    assert "No line items found" in result.output


def test_summary_by_station(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_line_items(db_path)
    result = runner.invoke(cli, ["--db", str(db_path), "summary", "--candidate", "Steyer"])
    assert result.exit_code == 0
    assert "KABC-TV" in result.output


def test_summary_by_show(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_line_items(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "summary", "--candidate", "Steyer", "--by", "show",
    ])
    assert result.exit_code == 0
    assert "NBA LA Lakers" in result.output
    assert "5A News" in result.output


def test_summary_json_output(runner, tmp_path):
    import json

    db_path = tmp_path / "test.db"
    _seed_line_items(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "summary", "--candidate", "Steyer", "--format", "json",
    ])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["total_spots"] == 6
    assert data[0]["total_spend"] == 27500.0


def test_query_format_json_no_results(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "query", "--format", "json"])
    assert result.exit_code == 0
    assert "[]" in result.output


# --- District CLI tests ---


def _seed_district_scenario(db_path):
    """Seed stations, contracts, and crosswalk for district CLI tests."""
    from fcc_ad_tracker.db.connection import get_connection
    from fcc_ad_tracker.db import queries
    from fcc_ad_tracker.districts import insert_crosswalk

    conn = get_connection(db_path)
    queries.upsert_station(conn, "E001", "KABC-TV", "LOS ANGELES", "LA", "CA", "Full Service")
    queries.upsert_station(conn, "E002", "KFMB-TV", "SAN DIEGO", "SD", "CA", "Full Service")
    queries.upsert_station(conn, "E003", "KHOU-TV", "HOUSTON", "Houston", "TX", "Full Service")

    queries.upsert_contract(
        conn, contract_id="E001:100", entity_id="E001", contract_number="100",
        advertiser="STEYER FOR GOV", candidate="Tom Steyer",
        gross_total=100000.0, net_total=85000.0, total_spots=50,
    )
    queries.upsert_contract(
        conn, contract_id="E002:200", entity_id="E002", contract_number="200",
        advertiser="STEYER FOR GOV", candidate="Tom Steyer",
        gross_total=60000.0, net_total=51000.0, total_spots=30,
    )
    queries.upsert_contract(
        conn, contract_id="E003:300", entity_id="E003", contract_number="300",
        advertiser="CRUZ CAMPAIGN", candidate="Ted Cruz",
        gross_total=200000.0, net_total=170000.0, total_spots=100,
    )

    crosswalk = [
        {"state": "CA", "district": "CA-27", "dma_name": "Los Angeles",
         "population": 950000, "weight": 1.0},
        {"state": "CA", "district": "CA-48", "dma_name": "Los Angeles",
         "population": 284000, "weight": 0.331},
        {"state": "CA", "district": "CA-48", "dma_name": "San Diego",
         "population": 574000, "weight": 0.669},
        {"state": "TX", "district": "TX-22", "dma_name": "Houston",
         "population": 780000, "weight": 1.0},
    ]
    market_map = {
        "Los Angeles": "LOS ANGELES",
        "San Diego": "SAN DIEGO",
        "Houston": "HOUSTON",
    }
    insert_crosswalk(conn, crosswalk, market_map)
    conn.close()


def test_load_districts_command(runner, tmp_path):
    import textwrap

    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "crosswalk.csv"
    csv_path.write_text(textwrap.dedent("""\
        CD,Media market,State,Population,Percentage
        CA-27,Los Angeles,CA,"952,345",100.0%
        CA-48,Los Angeles,CA,"284,102",33.1%
        CA-48,San Diego,CA,"573,898",66.9%
    """))

    # Seed a station so auto-match has something to find
    from fcc_ad_tracker.db.connection import get_connection
    from fcc_ad_tracker.db import queries
    conn = get_connection(db_path)
    queries.upsert_station(conn, "E001", "KABC-TV", "LOS ANGELES", "LA", "CA", "Full Service")
    conn.close()

    result = runner.invoke(cli, [
        "--db", str(db_path), "load-districts", "--input", str(csv_path),
    ])
    assert result.exit_code == 0
    assert "Loaded 3 district-DMA mappings" in result.output
    assert "Matched 1/" in result.output
    assert "Downballot" in result.output


def test_load_districts_unmatched_report(runner, tmp_path):
    import textwrap

    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "crosswalk.csv"
    csv_path.write_text(textwrap.dedent("""\
        CD,Media market,State,Population,Percentage
        CA-27,Los Angeles,CA,"952,345",100.0%
    """))

    result = runner.invoke(cli, [
        "--db", str(db_path), "load-districts", "--input", str(csv_path),
    ])
    assert result.exit_code == 0
    assert "1 unmatched" in result.output
    assert "Los Angeles" in result.output


def test_map_dma_command(runner, tmp_path):
    import textwrap

    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "crosswalk.csv"
    csv_path.write_text(textwrap.dedent("""\
        CD,Media market,State,Population,Percentage
        CA-27,Sacramento-Stockton-Modesto,CA,"952,345",100.0%
    """))

    result = runner.invoke(cli, [
        "--db", str(db_path), "load-districts", "--input", str(csv_path),
    ])
    assert result.exit_code == 0

    result = runner.invoke(cli, [
        "--db", str(db_path), "map-dma",
        "Sacramento-Stockton-Modesto", "SACRAMNTO-STKTON-MODESTO",
    ])
    assert result.exit_code == 0
    assert "1 rows updated" in result.output


def test_map_dma_no_match(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, [
        "--db", str(db_path), "map-dma", "Nonexistent", "WHATEVER",
    ])
    assert result.exit_code == 0
    assert "No rows found" in result.output


def test_contracts_district_table(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "contracts", "--district", "CA-27",
    ])
    assert result.exit_code == 0
    assert "KABC-TV" in result.output
    assert "100.0%" in result.output


def test_contracts_district_json(runner, tmp_path):
    import json

    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "contracts", "--district", "CA-27", "--format", "json",
    ])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["district"] == "CA-27"
    assert data[0]["estimated_gross"] == pytest.approx(100000.0)


def test_contracts_district_csv(runner, tmp_path):
    import csv
    import io

    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "contracts", "--district", "CA-48", "--format", "csv",
    ])
    assert result.exit_code == 0
    reader = csv.DictReader(io.StringIO(result.output))
    rows = list(reader)
    assert len(rows) == 2  # LA + SD DMAs
    assert "estimated_gross" in rows[0]


def test_contracts_district_no_results(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "contracts", "--district", "FL-99",
    ])
    assert result.exit_code == 0
    assert "No contracts found for FL-99" in result.output


def test_contracts_district_with_candidate(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "contracts", "--district", "TX-22", "--candidate", "Cruz",
    ])
    assert result.exit_code == 0
    assert "Ted Cruz" in result.output

    result = runner.invoke(cli, [
        "--db", str(db_path), "contracts", "--district", "TX-22", "--candidate", "Nobody",
    ])
    assert result.exit_code == 0
    assert "No contracts found" in result.output


def test_summary_by_district(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "summary", "--by", "district", "--candidate", "Steyer",
    ])
    assert result.exit_code == 0
    assert "CA-27" in result.output
    assert "CA-48" in result.output


def test_summary_by_district_state_filter(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "summary", "--by", "district", "--state", "TX",
    ])
    assert result.exit_code == 0
    assert "TX-22" in result.output
    assert "CA-27" not in result.output


def test_summary_by_district_json(runner, tmp_path):
    import json

    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "summary", "--by", "district",
        "--candidate", "Steyer", "--format", "json",
    ])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) >= 2
    districts = {d["district"] for d in data}
    assert "CA-27" in districts
    assert all("estimated_gross" in d for d in data)


def test_summary_by_district_no_results(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, [
        "--db", str(db_path), "summary", "--by", "district",
    ])
    assert result.exit_code == 0
    assert "No district-level" in result.output


def test_summary_single_district(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "summary", "--district", "CA-48",
    ])
    assert result.exit_code == 0
    # Should show DMA weight breakdown
    assert "Los Angeles" in result.output
    assert "San Diego" in result.output
    assert "estimated_gross" in result.output


def test_summary_single_district_json(runner, tmp_path):
    import json

    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "summary", "--district", "CA-27", "--format", "json",
    ])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["district"] == "CA-27"


def test_cli_creates_jsonl_log(runner, tmp_path):
    """CLI run should create a JSONL log file in data/logs/."""
    db_path = tmp_path / "test.db"
    log_dir = tmp_path / "logs"
    result = runner.invoke(cli, ["--db", str(db_path), "--log-dir", str(log_dir), "status"])
    assert result.exit_code == 0
    log_files = list(log_dir.glob("*.jsonl"))
    assert len(log_files) == 1
    assert "status" in log_files[0].name


def test_no_cache_prevents_cache_files(runner, tmp_path):
    """--no-cache flag should prevent cache file creation."""
    db_path = tmp_path / "test.db"
    cache_dir = tmp_path / "cache"
    log_dir = tmp_path / "logs"
    result = runner.invoke(cli, [
        "--db", str(db_path), "--log-dir", str(log_dir),
        "--no-cache", "status",
    ])
    assert result.exit_code == 0
    assert not cache_dir.exists()


def test_quiet_suppresses_log_message(runner, tmp_path):
    """--quiet should suppress 'Log: ...' message from stderr."""
    db_path = tmp_path / "test.db"
    log_dir = tmp_path / "logs"
    result = runner.invoke(cli, [
        "--db", str(db_path), "--log-dir", str(log_dir), "--quiet", "status",
    ])
    assert result.exit_code == 0
    assert "Log:" not in result.output


@patch("fcc_ad_tracker.download.download_pdf")
def test_download_writes_log_events(mock_dl, runner, tmp_path):
    """Download command should write events to the scratchpad log."""
    db_path = str(tmp_path / "test.db")
    log_dir = tmp_path / "logs"
    _seed_station(db_path)

    from unittest.mock import MagicMock, patch as _patch

    client_mock = MagicMock()
    client_mock.get_file_history.return_value = _fake_history(1)

    call_count = {"n": 0}
    def _unique_sha(_path):
        call_count["n"] += 1
        return f"sha-{call_count['n']}"

    with _patch("fcc_ad_tracker.cli._make_client") as mock_make:
        mock_make.return_value = client_mock
        with _patch("fcc_ad_tracker.download.sha256_file", side_effect=_unique_sha):
            result = runner.invoke(cli, [
                "--db", db_path, "--log-dir", str(log_dir),
                "download", "--station", "KABC-TV",
            ])

    assert result.exit_code == 0
    log_files = list(log_dir.glob("*.jsonl"))
    assert len(log_files) >= 1
    log_text = log_files[0].read_text().strip()
    assert len(log_text) > 0  # At least one event logged


def test_summary_single_district_no_results(runner, tmp_path):
    db_path = tmp_path / "test.db"
    _seed_district_scenario(db_path)
    result = runner.invoke(cli, [
        "--db", str(db_path), "summary", "--district", "FL-99",
    ])
    assert result.exit_code == 0
    assert "No ad exposure found for FL-99" in result.output
