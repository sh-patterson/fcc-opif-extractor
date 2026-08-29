"""Readiness checks for the optional Gemini extraction runtime."""

from __future__ import annotations

import importlib.util
import os


def gemini_readiness() -> tuple[bool, str | None]:
    """Return whether Gemini extraction can run and why it cannot."""
    try:
        package_installed = importlib.util.find_spec("google.genai") is not None
    except ModuleNotFoundError:
        package_installed = False

    if not package_installed:
        return False, "google-genai is not installed; install fcc-ad-tracker[gemini]"
    if not os.environ.get("GOOGLE_API_KEY"):
        return False, "GOOGLE_API_KEY is not set"
    return True, None
