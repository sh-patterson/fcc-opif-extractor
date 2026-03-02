import threading

from fcc_ad_tracker.cache import FileCache


def test_miss_returns_none(tmp_path):
    cache = FileCache(tmp_path)
    assert cache.get("facilities", "nonexistent") is None


def test_set_then_get_roundtrip(tmp_path):
    cache = FileCache(tmp_path)
    payload = {"results": [{"id": "1", "name": "KABC"}]}
    key = FileCache.make_key("facilities", "https://api.fcc.gov/search/CA.json")
    cache.set("facilities", key, payload)
    result = cache.get("facilities", key)
    assert result == payload


def test_expired_entry_returns_none(tmp_path):
    cache = FileCache(tmp_path)
    key = FileCache.make_key("facilities", "https://api.fcc.gov/search/CA.json")
    cache.set("facilities", key, {"data": 1}, ttl_seconds=0)
    # TTL=0 means already expired
    import time
    time.sleep(0.01)
    assert cache.get("facilities", key) is None


def test_no_expiry_persists(tmp_path):
    cache = FileCache(tmp_path)
    key = FileCache.make_key("facilities", "https://api.fcc.gov/search/CA.json")
    cache.set("facilities", key, {"data": 1}, ttl_seconds=None)
    result = cache.get("facilities", key)
    assert result == {"data": 1}


def test_corrupted_file_returns_none(tmp_path):
    cache = FileCache(tmp_path)
    ns_dir = tmp_path / "facilities"
    ns_dir.mkdir()
    (ns_dir / "badfile.json").write_text("not valid json{{{")
    assert cache.get("facilities", "badfile") is None


def test_make_key_deterministic():
    k1 = FileCache.make_key("ns", "https://example.com", {"a": "1", "b": "2"})
    k2 = FileCache.make_key("ns", "https://example.com", {"a": "1", "b": "2"})
    assert k1 == k2


def test_make_key_varies_by_params():
    k1 = FileCache.make_key("ns", "https://example.com", {"state": "CA"})
    k2 = FileCache.make_key("ns", "https://example.com", {"state": "TX"})
    assert k1 != k2


def test_atomic_write_no_partial_files(tmp_path):
    """After set(), only the final file should exist — no .tmp leftovers."""
    cache = FileCache(tmp_path)
    key = FileCache.make_key("test", "https://example.com")
    cache.set("test", key, {"data": "ok"})
    ns_dir = tmp_path / "test"
    files = list(ns_dir.iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".json"
    assert not any(f.name.endswith(".tmp") for f in files)


def test_thread_safe_concurrent_writes(tmp_path):
    """Multiple threads writing to the same cache should not corrupt data."""
    cache = FileCache(tmp_path)
    errors = []

    def writer(thread_id):
        try:
            for i in range(25):
                key = FileCache.make_key("concurrent", f"url-{thread_id}-{i}")
                cache.set("concurrent", key, {"thread": thread_id, "i": i})
                result = cache.get("concurrent", key)
                assert result is not None, f"Thread {thread_id} lost write {i}"
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Concurrent write errors: {errors}"
    # All 100 entries should be on disk
    ns_dir = tmp_path / "concurrent"
    assert len(list(ns_dir.iterdir())) == 100
