from fcc_ca_ads.config import OpifConfig, CA_TARGET_DMAS


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
    assert "LOS ANGELES" in CA_TARGET_DMAS
    assert "SACRAMNTO-STKTON-MODESTO" in CA_TARGET_DMAS
    assert len(CA_TARGET_DMAS) == 4
