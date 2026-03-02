"""Regex-based field extraction with confidence scoring for FCC political ad PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass

CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class FieldMatch:
    field_name: str
    value: str
    confidence: str  # "high", "medium", "low"
    page_number: int = 0


def extract_advertiser(text: str, page: int = 0) -> list[FieldMatch]:
    """Extract advertiser from text with confidence scoring."""
    matches: list[FieldMatch] = []

    # High: labeled "Advertiser:" on same line
    for m in re.finditer(r"(?i)advertiser\s*:\s*(.+)", text):
        matches.append(FieldMatch("advertiser", m.group(1).strip(), "high", page))

    # High: FCC contract format — "NAME FOR GOVERNOR/CONGRESS 2026" pattern as committee name
    for m in re.finditer(
        r"([A-Z][A-Z ]+?)\s+FOR\s+(?:GOVERNOR|CONGRESS|SENATE|ASSEMBLY)\s*\d{0,4}",
        text,
    ):
        val = m.group(0).strip()
        if val and len(val) > 5:
            matches.append(FieldMatch("advertiser", val, "high", page))

    # Medium: "Ordered By:" or "Paid for by" (as advertiser)
    for m in re.finditer(r"(?i)ordered\s+by\s*:\s*(.+)", text):
        matches.append(FieldMatch("advertiser", m.group(1).strip(), "medium", page))

    for m in re.finditer(r"(?i)paid\s+for\s+by\s+(.+?)(?:\s+for\s+|$)", text):
        matches.append(FieldMatch("advertiser", m.group(1).strip(), "medium", page))

    return _sort_by_confidence(matches)


def extract_candidate(text: str, page: int = 0) -> list[FieldMatch]:
    """Extract candidate name from text with confidence scoring."""
    matches: list[FieldMatch] = []

    # High: labeled "Candidate:"
    for m in re.finditer(r"(?i)candidate\s*:\s*(.+)", text):
        val = m.group(1).strip()
        # Trim trailing "for Congress" etc. if present
        val = re.sub(r"\s+for\s+(?:congress|senate|governor|assembly|legislature).*", "", val, flags=re.IGNORECASE)
        if val:
            matches.append(FieldMatch("candidate", val, "high", page))

    # High: FCC contract format — "NAME FOR GOVERNOR/CONGRESS/SENATE" ALL-CAPS advertiser field
    for m in re.finditer(
        r"([A-Z][A-Z ]+?)\s+FOR\s+(GOVERNOR|CONGRESS|SENATE|ASSEMBLY|LEGISLATURE)",
        text,
    ):
        val = m.group(1).strip().title()
        if val and len(val) > 3:
            matches.append(FieldMatch("candidate", val, "high", page))

    # Medium: "X for Congress/Senate/Governor/Assembly" mixed case pattern
    for m in re.finditer(
        r"(?i)(?:paid\s+for\s+by\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"
        r"\s+for\s+(?:congress|senate|governor|assembly|legislature)",
        text,
    ):
        matches.append(FieldMatch("candidate", m.group(1).strip(), "medium", page))

    return _sort_by_confidence(matches)


def extract_total(text: str, page: int = 0) -> list[FieldMatch]:
    """Extract total dollar amount from text with confidence scoring."""
    matches: list[FieldMatch] = []

    # High: labeled total ("Gross Total:", "Total:", "Net Total:", "Total Amount:")
    for m in re.finditer(
        r"(?i)(?:gross\s+)?(?:net\s+)?total(?:\s+amount)?\s*:\s*(\$[\d,]+(?:\.\d{2})?)",
        text,
    ):
        matches.append(FieldMatch("total", m.group(1).strip(), "high", page))

    # Low: bare dollar amount >= $1,000 with no label
    for m in re.finditer(r"(\$[\d,]+(?:\.\d{2})?)", text):
        amount_str = m.group(1).replace("$", "").replace(",", "")
        try:
            amount = float(amount_str)
        except ValueError:
            continue
        if amount < 1000:
            continue
        # Skip if this was already captured by a labeled pattern
        start = max(0, m.start() - 40)
        prefix = text[start : m.start()]
        if re.search(r"(?i)(?:gross\s+)?(?:net\s+)?total", prefix):
            continue
        matches.append(FieldMatch("total", m.group(1), "low", page))

    return _sort_by_confidence(matches)


def extract_flight_dates(text: str, page: int = 0) -> list[FieldMatch]:
    """Extract flight date ranges from text with confidence scoring."""
    matches: list[FieldMatch] = []

    date_pat = r"\d{1,2}/\d{1,2}/\d{2,4}"
    range_pat = rf"({date_pat})\s*[-–—]\s*({date_pat})"

    # High: labeled "Flight:", "Flight Dates:", "Air Dates:", "Contract Dates:"
    for m in re.finditer(
        rf"(?i)(?:flight|air|contract)\s*(?:dates?)?\s*:?\s*(?:estimate\s*#?\s*)?{range_pat}",
        text,
    ):
        value = f"{m.group(1)} - {m.group(2)}"
        matches.append(FieldMatch("flight_dates", value, "high", page))

    # High: "Contract Dates" header with date range on next line
    for m in re.finditer(
        rf"(?i)contract\s+dates.*?\n\s*{range_pat}", text
    ):
        value = f"{m.group(1)} - {m.group(2)}"
        matches.append(FieldMatch("flight_dates", value, "high", page))

    # Medium: unlabeled date range
    for m in re.finditer(range_pat, text):
        value = f"{m.group(1)} - {m.group(2)}"
        # Skip if already captured by labeled pattern
        start = max(0, m.start() - 40)
        prefix = text[start : m.start()]
        if re.search(r"(?i)(?:flight|air|contract)\s*(?:dates?)?\s*:?", prefix):
            continue
        matches.append(FieldMatch("flight_dates", value, "medium", page))

    return _sort_by_confidence(matches)


def extract_all_fields(text: str, page: int = 0) -> list[FieldMatch]:
    """Run all extractors and return the best match per field name."""
    if not text or not text.strip():
        return []

    all_matches: list[FieldMatch] = []
    all_matches.extend(extract_advertiser(text, page))
    all_matches.extend(extract_candidate(text, page))
    all_matches.extend(extract_total(text, page))
    all_matches.extend(extract_flight_dates(text, page))

    # Keep only the best (highest confidence) match per field name
    best: dict[str, FieldMatch] = {}
    for m in all_matches:
        if m.field_name not in best:
            best[m.field_name] = m
        elif CONFIDENCE_ORDER[m.confidence] < CONFIDENCE_ORDER[best[m.field_name].confidence]:
            best[m.field_name] = m

    return list(best.values())


def _sort_by_confidence(matches: list[FieldMatch]) -> list[FieldMatch]:
    """Sort matches by confidence (high first)."""
    return sorted(matches, key=lambda m: CONFIDENCE_ORDER[m.confidence])
