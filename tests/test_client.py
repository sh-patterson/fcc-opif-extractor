import json
from pathlib import Path

import responses

from fcc_ca_ads.client import OpifClient
from fcc_ca_ads.config import OpifConfig

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@responses.activate
def test_get_parent_folders():
    cfg = OpifConfig(rate_limit_delay=0.0)
    client = OpifClient(cfg)
    entity_id = "25452"
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/folder/parentFolders.json",
        json=load_fixture("parent_folders.json"),
        status=200,
    )
    result = client.get_parent_folders(entity_id)
    assert result["status"] == "success"
    assert "subFolders" in result["results"]


@responses.activate
def test_get_folder():
    cfg = OpifConfig(rate_limit_delay=0.0)
    client = OpifClient(cfg)
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/folder/id/folder-abc.json",
        json=load_fixture("folder_detail.json"),
        status=200,
    )
    result = client.get_folder("folder-abc", "25452")
    assert result["status"] == "success"


@responses.activate
def test_search_facilities():
    cfg = OpifConfig(rate_limit_delay=0.0)
    client = OpifClient(cfg)
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/service/tv/facility/search/CA.json",
        json=load_fixture("facility_search_ca.json"),
        status=200,
    )
    result = client.search_facilities("CA")
    assert result["status"] == "OK"
    assert len(result["results"]["searchList"]) > 0


@responses.activate
def test_get_download_url():
    cfg = OpifConfig(rate_limit_delay=0.0)
    client = OpifClient(cfg)
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/download/folder-abc/file-123.pdf",
        status=302,
        headers={"Location": "https://files.fcc.gov/some/path.pdf"},
    )
    url = client.get_download_url("folder-abc", "file-123")
    assert "files.fcc.gov" in url


@responses.activate
def test_retry_on_server_error():
    cfg = OpifConfig(
        rate_limit_delay=0.0,
        max_retries=2,
        retry_backoff_base=0.01,
        retry_jitter_max=0.0,
    )
    client = OpifClient(cfg)
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/folder/parentFolders.json",
        status=503,
    )
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/folder/parentFolders.json",
        status=503,
    )
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/folder/parentFolders.json",
        json=load_fixture("parent_folders.json"),
        status=200,
    )
    result = client.get_parent_folders("25452")
    assert result["status"] == "success"
    assert len(responses.calls) == 3


@responses.activate
def test_file_history():
    cfg = OpifConfig(rate_limit_delay=0.0)
    client = OpifClient(cfg)
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/file/history.json",
        json=load_fixture("file_history.json"),
        status=200,
    )
    result = client.get_file_history("25452", "2026-01-01", "2026-03-01")
    assert len(result) == 2
    assert result[0]["file_name"] == "ABC_PAC_Order_20260215"


@responses.activate
def test_file_history_empty():
    cfg = OpifConfig(rate_limit_delay=0.0)
    client = OpifClient(cfg)
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/file/history.json",
        json=load_fixture("file_history_empty.json"),
        status=200,
    )
    result = client.get_file_history("25452", "2026-01-01", "2026-03-01")
    assert result == []
