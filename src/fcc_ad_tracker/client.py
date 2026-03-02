import logging
import random
import threading
import time

import requests

from fcc_ca_ads.config import OpifConfig

logger = logging.getLogger(__name__)


class OpifClient:
    def __init__(self, config: OpifConfig | None = None):
        self.config = config or OpifConfig()
        self.session = requests.Session()
        self._last_request_time = 0.0
        self._rate_lock = threading.Lock()

    def _rate_limit(self):
        with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self.config.rate_limit_delay:
                time.sleep(self.config.rate_limit_delay - elapsed)
            self._last_request_time = time.monotonic()

    def _request(
        self, method: str, path: str, *, allow_redirects: bool = True, **kwargs
    ) -> requests.Response:
        url = f"{self.config.base_url}{path}"
        kwargs.setdefault("timeout", self.config.request_timeout)

        for attempt in range(self.config.max_retries + 1):
            self._rate_limit()
            try:
                resp = self.session.request(
                    method, url, allow_redirects=allow_redirects, **kwargs
                )
                if resp.status_code not in self.config.retryable_status_codes:
                    return resp
                logger.warning(
                    "Retryable status %d on %s (attempt %d)",
                    resp.status_code,
                    path,
                    attempt + 1,
                )
            except requests.RequestException as exc:
                logger.warning("Request error on %s (attempt %d): %s", path, attempt + 1, exc)
                if attempt == self.config.max_retries:
                    raise

            if attempt < self.config.max_retries:
                delay = min(
                    self.config.retry_backoff_base ** (attempt + 1),
                    self.config.retry_backoff_max,
                )
                delay += random.uniform(0, self.config.retry_jitter_max)
                time.sleep(delay)

        resp.raise_for_status()
        return resp  # unreachable in practice

    def get_parent_folders(self, entity_id: str) -> dict:
        resp = self._request(
            "GET",
            "/api/manager/folder/parentFolders.json",
            params={"entityId": entity_id, "sourceService": "tv"},
        )
        resp.raise_for_status()
        return resp.json()

    def get_folder(self, folder_id: str, entity_id: str) -> dict:
        resp = self._request(
            "GET",
            f"/api/manager/folder/id/{folder_id}.json",
            params={"entityId": entity_id},
        )
        resp.raise_for_status()
        return resp.json()

    def get_file_history(
        self,
        entity_id: str,
        start_date: str,
        end_date: str,
        count: int = 100,
        offset: int = 0,
    ) -> list:
        resp = self._request(
            "GET",
            "/api/manager/file/history.json",
            params={
                "entityId": entity_id,
                "sourceService": "tv",
                "startDate": start_date,
                "endDate": end_date,
                "count": count,
                "offset": offset,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        # "File History Not Found" is a valid empty response
        if isinstance(data, dict) and data.get("status") == "error":
            return []
        # Live API uses "history" key at top level
        if "history" in data:
            return data["history"]
        # Fallback for older/alternate response shape
        results = data.get("results", {})
        return results.get("fileHistory", []) if isinstance(results, dict) else []

    def get_download_url(self, folder_id: str, file_manager_id: str) -> str:
        resp = self._request(
            "GET",
            f"/api/manager/download/{folder_id}/{file_manager_id}.pdf",
            allow_redirects=False,
        )
        if resp.status_code == 302:
            return resp.headers["Location"]
        resp.raise_for_status()
        return resp.url

    def search_facilities(self, state: str) -> dict:
        resp = self._request("GET", f"/api/service/tv/facility/search/{state}.json")
        resp.raise_for_status()
        return resp.json()
