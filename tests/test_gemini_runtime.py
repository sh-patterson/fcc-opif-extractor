from unittest.mock import patch

from fcc_ad_tracker.gemini_runtime import gemini_readiness


def test_gemini_readiness_reports_missing_package():
    with patch("importlib.util.find_spec", return_value=None):
        ready, reason = gemini_readiness()

    assert ready is False
    assert "google-genai is not installed" in reason


def test_gemini_readiness_reports_missing_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with patch("importlib.util.find_spec", return_value=object()):
        ready, reason = gemini_readiness()

    assert ready is False
    assert reason == "GOOGLE_API_KEY is not set"


def test_gemini_readiness_accepts_package_and_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    with patch("importlib.util.find_spec", return_value=object()):
        ready, reason = gemini_readiness()

    assert ready is True
    assert reason is None
