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
