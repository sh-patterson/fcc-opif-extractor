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
    form_type_match = re.search(r"\bPB-(18|19)\b", text_u)
    has_nab_title = bool(
        re.search(r"\bNAB\s+FORM\s+PB-(?:18|19)\b", text_u)
        or re.search(
            r"POLITICAL\s+BROADCAST\s+AGREEMENT\s+FORM[\s\S]{0,100}\(PB-(?:18|19)\)",
            text_u,
        )
    )
    if not has_nab_title or form_type_match is None:
        return None

    form_type = f"PB-{form_type_match.group(1)}"
    horizontal = r"[^\S\r\n]*"
    value = r"([^\r\n]+)"
    candidate = None
    if form_type == "PB-18":
        candidate = _capture_first(
            rf"^{horizontal}(?:candidate(?:{horizontal}name)?|name)"
            rf"{horizontal}:{horizontal}{value}$",
            text,
        )
    office = _capture_first(
        rf"^{horizontal}office(?:{horizontal}sought)?{horizontal}:{horizontal}{value}$",
        text,
    )
    party = _capture_first(
        rf"^{horizontal}party(?:{horizontal}affiliation)?{horizontal}:{horizontal}{value}$",
        text,
    )
    level = _capture_first(
        rf"^{horizontal}(?:federal|state|local){horizontal}(?:office)?"
        rf"{horizontal}:{horizontal}{value}$",
        text,
    )

    return NabFormData(
        form_type=form_type,
        candidate_name=candidate,
        office_sought=office,
        party_affiliation=party,
        election_level=level,
    )
