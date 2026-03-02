import json
import threading
from datetime import datetime
from pathlib import Path

from fcc_ad_tracker.scratchpad import Scratchpad


def test_creates_file(tmp_path):
    path = tmp_path / "run.jsonl"
    sp = Scratchpad(path)
    sp.log("test_event", key="value")
    sp.close()
    assert path.exists()


def test_writes_valid_jsonl(tmp_path):
    path = tmp_path / "run.jsonl"
    sp = Scratchpad(path)
    sp.log("api_call", url="/api/test", status=200)
    sp.log("download", file_id="F001")
    sp.close()

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        data = json.loads(line)  # Must be valid JSON
        assert "event_type" in data
        assert "timestamp" in data


def test_appends_each_entry_own_line(tmp_path):
    path = tmp_path / "run.jsonl"
    sp = Scratchpad(path)
    for i in range(5):
        sp.log("event", index=i)
    sp.close()

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 5


def test_iso8601_timestamps(tmp_path):
    path = tmp_path / "run.jsonl"
    sp = Scratchpad(path)
    sp.log("test")
    sp.close()

    entry = json.loads(path.read_text().strip())
    # Should parse as ISO 8601
    ts = datetime.fromisoformat(entry["timestamp"])
    assert ts.year >= 2026


def test_thread_safe_concurrent_writes(tmp_path):
    path = tmp_path / "run.jsonl"
    sp = Scratchpad(path)
    errors = []

    def writer(thread_id):
        try:
            for i in range(25):
                sp.log("concurrent", thread=thread_id, index=i)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sp.close()

    assert errors == []
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 100


def test_context_manager(tmp_path):
    path = tmp_path / "run.jsonl"
    with Scratchpad(path) as sp:
        sp.log("inside")
    # File should be closed and readable
    entry = json.loads(path.read_text().strip())
    assert entry["event_type"] == "inside"


def test_path_kwargs_serialize_as_str(tmp_path):
    path = tmp_path / "run.jsonl"
    sp = Scratchpad(path)
    sp.log("download", local_path=Path("/data/raw/KABC/file.pdf"))
    sp.close()

    entry = json.loads(path.read_text().strip())
    assert entry["local_path"] == "/data/raw/KABC/file.pdf"
    assert isinstance(entry["local_path"], str)
