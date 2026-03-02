import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class FileCache:
    def __init__(self, cache_dir: Path):
        self._cache_dir = cache_dir

    @staticmethod
    def make_key(namespace: str, url: str, params: dict | None = None) -> str:
        raw = f"{namespace}:{url}:{sorted((params or {}).items())}"
        return hashlib.md5(raw.encode()).hexdigest()[:8]

    def get(self, namespace: str, key: str) -> dict | None:
        path = self._cache_dir / namespace / f"{key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.debug("Corrupted cache file %s", path)
            return None
        expires_at = data.get("expires_at")
        if expires_at is not None:
            if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
                return None
        return data.get("payload")

    def set(
        self, namespace: str, key: str, payload: dict, ttl_seconds: int | None = None
    ) -> None:
        ns_dir = self._cache_dir / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        dest = ns_dir / f"{key}.json"

        expires_at = None
        if ttl_seconds is not None:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
            ).isoformat()

        envelope = {"expires_at": expires_at, "payload": payload}

        fd, tmp_path = tempfile.mkstemp(dir=ns_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(envelope, f)
            os.replace(tmp_path, dest)
        except BaseException:
            # Clean up temp file on any failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
