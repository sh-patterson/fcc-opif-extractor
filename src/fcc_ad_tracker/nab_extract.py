"""NAB PB-18 / PB-19 form extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NabFormData:
    form_type: str | None
    candidate_name: str | None
    office_sought: str | None
    party_affiliation: str | None
    election_level: str | None


def _capture_first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return None
    value = re.sub(r"\s+", " ", m.group(1)).strip(" :\t")
    return value or None


def extract_nab_form(text: str) -> NabFormData | None:
    if not text or not text.strip():
        return None
    text_u = text.upper()
    if "NAB FORM PB-18" not in text_u and "NAB FORM PB-19" not in text_u:
        return None

    form_type = "PB-18" if "PB-18" in text_u else ("PB-19" if "PB-19" in text_u else None)
    candidate = _capture_first(r"^\s*(?:candidate(?:\s*name)?|name)\s*:\s*(.+)$", text)
    office = _capture_first(r"^\s*office(?:\s+sought)?\s*:\s*(.+)$", text)
    party = _capture_first(r"^\s*party(?:\s+affiliation)?\s*:\s*(.+)$", text)
    level = _capture_first(
        r"^\s*(?:federal|state|local)\s*(?:office)?\s*:\s*(.+)$",
        text,
    )
    if level is None:
        # Fallback for checkbox-style text.
        if re.search(r"\bfederal\b", text, flags=re.IGNORECASE):
            level = "federal"
        elif re.search(r"\bstate\b", text, flags=re.IGNORECASE):
            level = "state"
        elif re.search(r"\blocal\b", text, flags=re.IGNORECASE):
            level = "local"

    return NabFormData(
        form_type=form_type,
        candidate_name=candidate,
        office_sought=office,
        party_affiliation=party,
        election_level=level,
    )
