import json
from pathlib import Path

import responses

from fcc_ad_tracker.client import OpifClient
from fcc_ad_tracker.config import OpifConfig

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


def test_rate_limiter_is_thread_safe():
    """Rate limiter uses a lock — concurrent calls should not raise."""
    import threading

    cfg = OpifConfig(rate_limit_delay=0.0)
    client = OpifClient(cfg)

    assert hasattr(client, "_rate_lock")
    assert isinstance(client._rate_lock, type(threading.Lock()))

    # Hammer _rate_limit from multiple threads to verify no race
    errors = []

    def call_rate_limit():
        try:
            for _ in range(20):
                client._rate_limit()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=call_rate_limit) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Race condition in rate limiter: {errors}"


@responses.activate
def test_cache_hit_skips_http(tmp_path):
    """Second call to search_facilities should hit cache, not HTTP."""
    cfg = OpifConfig(rate_limit_delay=0.0, cache_dir=tmp_path)
    client = OpifClient(cfg)
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/service/tv/facility/search/CA.json",
        json=load_fixture("facility_search_ca.json"),
        status=200,
    )
    # First call — HTTP
    r1 = client.search_facilities("CA")
    assert len(responses.calls) == 1
    # Second call — cache hit
    r2 = client.search_facilities("CA")
    assert len(responses.calls) == 1  # No new HTTP call
    assert r1 == r2


@responses.activate
def test_cache_miss_populates_file(tmp_path):
    """First call should create a cache file on disk."""
    cfg = OpifConfig(rate_limit_delay=0.0, cache_dir=tmp_path)
    client = OpifClient(cfg)
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/service/tv/facility/search/CA.json",
        json=load_fixture("facility_search_ca.json"),
        status=200,
    )
    client.search_facilities("CA")
    cache_dir = tmp_path / "facilities"
    assert cache_dir.exists()
    assert len(list(cache_dir.iterdir())) == 1


@responses.activate
def test_force_bypasses_cache(tmp_path):
    """force=True should always hit HTTP even if cache is warm."""
    cfg = OpifConfig(rate_limit_delay=0.0, cache_dir=tmp_path)
    client = OpifClient(cfg)
    fixture = load_fixture("facility_search_ca.json")
    responses.add(responses.GET, f"{cfg.base_url}/api/service/tv/facility/search/CA.json",
                  json=fixture, status=200)
    responses.add(responses.GET, f"{cfg.base_url}/api/service/tv/facility/search/CA.json",
                  json=fixture, status=200)
    client.search_facilities("CA")
    client.search_facilities("CA", force=True)
    assert len(responses.calls) == 2


@responses.activate
def test_no_cache_when_cache_dir_none():
    """When cache_dir is None (default), no caching occurs."""
    cfg = OpifConfig(rate_limit_delay=0.0)
    client = OpifClient(cfg)
    fixture = load_fixture("facility_search_ca.json")
    responses.add(responses.GET, f"{cfg.base_url}/api/service/tv/facility/search/CA.json",
                  json=fixture, status=200)
    responses.add(responses.GET, f"{cfg.base_url}/api/service/tv/facility/search/CA.json",
                  json=fixture, status=200)
    client.search_facilities("CA")
    client.search_facilities("CA")
    assert len(responses.calls) == 2  # Both hit HTTP


@responses.activate
def test_get_file_history_never_cached(tmp_path):
    """get_file_history should never be cached."""
    cfg = OpifConfig(rate_limit_delay=0.0, cache_dir=tmp_path)
    client = OpifClient(cfg)
    fixture = load_fixture("file_history.json")
    responses.add(responses.GET, f"{cfg.base_url}/api/manager/file/history.json",
                  json=fixture, status=200)
    responses.add(responses.GET, f"{cfg.base_url}/api/manager/file/history.json",
                  json=fixture, status=200)
    client.get_file_history("25452", "2026-01-01", "2026-03-01")
    client.get_file_history("25452", "2026-01-01", "2026-03-01")
    assert len(responses.calls) == 2


@responses.activate
def test_get_download_url_never_cached(tmp_path):
    """get_download_url should never be cached."""
    cfg = OpifConfig(rate_limit_delay=0.0, cache_dir=tmp_path)
    client = OpifClient(cfg)
    responses.add(responses.GET,
                  f"{cfg.base_url}/api/manager/download/folder-abc/file-123.pdf",
                  status=302, headers={"Location": "https://files.fcc.gov/path.pdf"})
    responses.add(responses.GET,
                  f"{cfg.base_url}/api/manager/download/folder-abc/file-123.pdf",
                  status=302, headers={"Location": "https://files.fcc.gov/path.pdf"})
    client.get_download_url("folder-abc", "file-123")
    client.get_download_url("folder-abc", "file-123")
    assert len(responses.calls) == 2


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
