from dataclasses import dataclass
from pathlib import Path

DEFAULT_TARGET_DMAS = [
    "LOS ANGELES",
    "SAN FRANCISCO-OAK-SAN JOSE",
    "SACRAMNTO-STKTON-MODESTO",
    "SAN DIEGO",
]


@dataclass(frozen=True)
class OpifConfig:
    base_url: str = "https://publicfiles.fcc.gov"
    rate_limit_delay: float = 1.0
    max_retries: int = 3
    retry_backoff_base: float = 2.0
    retry_backoff_max: float = 60.0
    retry_jitter_max: float = 1.0
    request_timeout: float = 30.0
    retryable_status_codes: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})
    cache_dir: Path | None = None
    log_dir: Path | None = None
