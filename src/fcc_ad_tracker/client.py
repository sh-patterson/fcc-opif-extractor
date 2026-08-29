import logging
import random
import threading
import time

import requests

from fcc_ad_tracker.cache import FileCache
from fcc_ad_tracker.config import OpifConfig

logger = logging.getLogger(__name__)


class OpifClient:
    def __init__(self, config: OpifConfig | None = None, scratchpad=None):
        self.config = config or OpifConfig()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "fcc-ad-tracker/1.0 (+https://publicfiles.fcc.gov)",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._last_request_time = 0.0
        self._rate_lock = threading.Lock()
        self._session_lock = threading.Lock()
        self._cache = FileCache(self.config.cache_dir) if self.config.cache_dir else None
        self._scratchpad = scratchpad

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
        t0 = time.monotonic()

        for attempt in range(self.config.max_retries + 1):
            self._rate_limit()
            try:
                with self._session_lock:
                    resp = self.session.request(
                        method, url, allow_redirects=allow_redirects, **kwargs
                    )
                if resp.status_code not in self.config.retryable_status_codes:
                    if self._scratchpad:
                        duration_ms = round((time.monotonic() - t0) * 1000)
                        self._scratchpad.log(
                            "api_call",
                            method=method, url=url,
                            params=kwargs.get("params"),
                            status_code=resp.status_code,
                            cache_hit=False,
                            duration_ms=duration_ms,
                        )
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

    _CACHE_TTL_24H = 86400

    def get_parent_folders(self, entity_id: str, *, force: bool = False) -> dict:
        url = "/api/manager/folder/parentFolders.json"
        params = {"entityId": entity_id, "sourceService": "tv"}
        if self._cache and not force:
            key = FileCache.make_key("folders", url, params)
            cached = self._cache.get("folders", key)
            if cached is not None:
                if self._scratchpad:
                    self._scratchpad.log(
                        "api_call", method="GET",
                        url=f"{self.config.base_url}{url}",
                        params=params, cache_hit=True,
                    )
                return cached
        resp = self._request("GET", url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if self._cache:
            key = FileCache.make_key("folders", url, params)
            self._cache.set("folders", key, data, ttl_seconds=self._CACHE_TTL_24H)
        return data

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
            message = str(data.get("message", "")).lower()
            if "not found" in message:
                return []
            raise ValueError(f"Unexpected file history error response: {data}")

        # Live API uses "history" key at top level
        if isinstance(data, dict) and isinstance(data.get("history"), list):
            return data["history"]

        # Fallback for older/alternate response shape
        if isinstance(data, dict):
            results = data.get("results", {})
            if isinstance(results, dict) and isinstance(results.get("fileHistory"), list):
                return results["fileHistory"]

        raise ValueError(
            f"Unexpected file history response shape ({type(data).__name__}): {data}"
        )

    def get_download_url(self, file_manager_id: str) -> str:
        return f"https://files.fcc.gov/download/{file_manager_id}.pdf"

    def download_bytes(self, url: str, *, timeout: int = 60) -> bytes:
        """Download binary content using client-level throttling/retry/session controls."""
        t0 = time.monotonic()
        for attempt in range(self.config.max_retries + 1):
            self._rate_limit()
            try:
                with self._session_lock:
                    resp = self.session.get(url, timeout=timeout)
                if resp.status_code not in self.config.retryable_status_codes:
                    resp.raise_for_status()
                    if self._scratchpad:
                        duration_ms = round((time.monotonic() - t0) * 1000)
                        self._scratchpad.log(
                            "api_call",
                            method="GET",
                            url=url,
                            status_code=resp.status_code,
                            cache_hit=False,
                            duration_ms=duration_ms,
                        )
                    return resp.content
                logger.warning(
                    "Retryable status %d on download %s (attempt %d)",
                    resp.status_code,
                    url,
                    attempt + 1,
                )
            except requests.RequestException as exc:
                logger.warning(
                    "Download request error on %s (attempt %d): %s",
                    url,
                    attempt + 1,
                    exc,
                )
                if attempt == self.config.max_retries:
                    raise

            if attempt < self.config.max_retries:
                delay = min(
                    self.config.retry_backoff_base ** (attempt + 1),
                    self.config.retry_backoff_max,
                )
                delay += random.uniform(0, self.config.retry_jitter_max)
                time.sleep(delay)

        raise RuntimeError(f"Failed to download after retries: {url}")

    def search_facilities(self, state: str, *, force: bool = False) -> dict:
        state = state.strip().upper()
        url = f"/api/service/facility/search/{state}"
        params = {"format": "json"}
        if self._cache and not force:
            key = FileCache.make_key("facilities", url, params)
            cached = self._cache.get("facilities", key)
            if cached is not None:
                if self._scratchpad:
                    self._scratchpad.log(
                        "api_call", method="GET",
                        url=f"{self.config.base_url}{url}",
                        params=params,
                        cache_hit=True,
                    )
                return cached
        resp = self._request("GET", url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if self._cache:
            key = FileCache.make_key("facilities", url, params)
            self._cache.set("facilities", key, data, ttl_seconds=self._CACHE_TTL_24H)
        return data

    def search_political_files(
        self,
        *,
        query: str = "*",
        source_service_code: str = "tv",
        political_file_type: str | None = None,
        office_type: str | None = None,
        campaign_year: str | None = None,
        page: int = 0,
        size: int = 100,
    ) -> list[dict]:
        """Search FCC political files via /search/api."""
        params = {
            "q": query,
            "source_service_code": source_service_code,
            "page": page,
            "size": size,
        }
        if political_file_type:
            params["political_file_type"] = political_file_type
        if office_type:
            params["office_type"] = office_type
        if campaign_year:
            params["campaign_year"] = campaign_year

        # FCC search API is hosted on fcc.gov (not publicfiles.fcc.gov).
        url = "https://www.fcc.gov/search/api"
        resp = self.session.get(url, params=params, timeout=self.config.request_timeout)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected search response shape: {type(data).__name__}")

        # Common search shapes.
        if isinstance(data.get("results"), list):
            return data["results"]
        if isinstance(data.get("items"), list):
            return data["items"]
        response = data.get("response")
        if isinstance(response, dict) and isinstance(response.get("docs"), list):
            return response["docs"]

        raise ValueError(f"Unexpected search response payload: {data}")

    def get_station_rss(self, call_sign: str) -> str:
        """Fetch station RSS feed XML."""
        headers = {
            "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.1"
        }
        candidates = [
            f"{self.config.base_url}/tv-profile/{call_sign}/rss/",
            f"{self.config.base_url}/tv-profile/{call_sign}/rss",
            f"https://www.fcc.gov/tv-profile/{call_sign}/rss/",
            f"https://www.fcc.gov/tv-profile/{call_sign}/rss",
        ]
        last_error: requests.HTTPError | None = None
        for url in candidates:
            self._rate_limit()
            with self._session_lock:
                resp = self.session.get(url, headers=headers, timeout=self.config.request_timeout)
            if resp.status_code == 200:
                return resp.text
            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                last_error = exc
                # 403/404 are common from some endpoints; try the next candidate.
                if resp.status_code in {403, 404}:
                    continue
                raise
        if last_error:
            raise last_error
        raise RuntimeError(f"Unable to fetch RSS feed for {call_sign}")
