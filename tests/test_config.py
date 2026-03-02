from pathlib import Path

from fcc_ad_tracker.config import OpifConfig, DEFAULT_TARGET_DMAS


def test_default_config():
    cfg = OpifConfig()
    assert cfg.base_url == "https://publicfiles.fcc.gov"
    assert cfg.rate_limit_delay == 1.0
    assert cfg.max_retries == 3
    assert cfg.request_timeout == 30.0


def test_config_is_frozen():
    cfg = OpifConfig()
    try:
        cfg.base_url = "http://evil.com"
        assert False, "Should have raised"
    except AttributeError:
        pass


def test_ca_target_dmas():
    assert "LOS ANGELES" in DEFAULT_TARGET_DMAS
    assert "SACRAMNTO-STKTON-MODESTO" in DEFAULT_TARGET_DMAS
    assert len(DEFAULT_TARGET_DMAS) == 4


def test_cache_and_log_dirs_default_none():
    cfg = OpifConfig()
    assert cfg.cache_dir is None
    assert cfg.log_dir is None


def test_cache_and_log_dirs_accept_path():
    cfg = OpifConfig(cache_dir=Path("/tmp/cache"), log_dir=Path("/tmp/logs"))
    assert cfg.cache_dir == Path("/tmp/cache")
    assert cfg.log_dir == Path("/tmp/logs")
