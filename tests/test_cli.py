from unittest.mock import patch

import pytest
from click.testing import CliRunner

from fcc_ca_ads.cli import cli
from fcc_ca_ads.discover import Station


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "FCC California Political Ad" in result.output


def test_status_command(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "status"])
    assert result.exit_code == 0
    assert "Stations: 0" in result.output


@patch("fcc_ca_ads.cli.discover_stations")
@patch("fcc_ca_ads.cli.save_stations")
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
    from fcc_ca_ads.db.connection import get_connection
    from fcc_ca_ads.db import queries as q

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


@patch("fcc_ca_ads.download.download_pdf")
@patch("fcc_ca_ads.download.sha256_file", return_value="deadbeef")
def test_download_station_serial(mock_sha, mock_dl, runner, tmp_path):
    """_download_station with workers=1 downloads files and records them in DB."""
    from fcc_ca_ads.cli import _download_station
    from fcc_ca_ads.db.connection import get_connection
    from fcc_ca_ads.db import queries as q
    from unittest.mock import MagicMock

    db_path = str(tmp_path / "test.db")
    _seed_station(db_path)

    client = MagicMock()
    client.get_file_history.return_value = _fake_history(3)

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
        assert f["sha256"] == "deadbeef"


@patch("fcc_ca_ads.download.download_pdf")
@patch("fcc_ca_ads.download.sha256_file", return_value="deadbeef")
def test_download_station_concurrent(mock_sha, mock_dl, runner, tmp_path):
    """_download_station with workers=2 downloads files concurrently and records all in DB."""
    from fcc_ca_ads.cli import _download_station
    from fcc_ca_ads.db.connection import get_connection
    from fcc_ca_ads.db import queries as q
    from unittest.mock import MagicMock

    db_path = str(tmp_path / "test.db")
    _seed_station(db_path)

    client = MagicMock()
    client.get_file_history.return_value = _fake_history(4)

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
        assert f["sha256"] == "deadbeef"


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
    from fcc_ca_ads.db.connection import get_connection
    from fcc_ca_ads.db import queries

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


def test_query_format_json_no_results(runner, tmp_path):
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "query", "--format", "json"])
    assert result.exit_code == 0
    assert "[]" in result.output
