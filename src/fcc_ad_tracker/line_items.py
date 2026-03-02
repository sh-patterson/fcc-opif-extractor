"""Line-item extraction from FCC political ad contract PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class LineItem:
    line_number: int
    channel: str
    start_date: str
    end_date: str
    show_name: str
    time_slot: str
    spot_length: str  # ':30', ':15', ':15/:15'
    rate_per_spot: float | None
    rate_type: str  # 'NM', 'BK', 'CDR'
    spots: int
    line_total: float


# Pattern anchors:
# - Starts with "N <digits>" (line marker)
# - Channel is a short uppercase word (KABC, KCBS, etc.)
# - Two dates (MM/DD/YY or MM/DD/YYYY)
# - Show name (variable-length text, captured by matching up to spot length)
# - Time slot(s) embedded in show name capture (stripped later)
# - Spot length (:30, :15, :15/:15)
# - Optional rate per spot (dollar amount)
# - Optional PCode (CDR) before rate type
# - Rate type (NM, BK)
# - Spot count (digits)
# - Dollar amount for line total
#
# Strategy: anchor on spot length (:\d{2}) and work outward.
# The show_name + time_slot region is captured greedily, then split.
_LINE_ITEM_RE = re.compile(
    r"^N\s+(\d+)"                                    # 1: line number
    r"\s+([A-Z]{3,5})"                               # 2: channel
    r"\s+(\d{2}/\d{2}/\d{2,4})"                      # 3: start date
    r"\s+(\d{2}/\d{2}/\d{2,4})"                      # 4: end date
    r"\s+(.+?)"                                       # 5: show name (non-greedy)
    r"\s+((?:\d{1,2}(?::?\d{2})?(?:\s*[apAP](?:[mM])?)?-\d{1,2}(?::?\d{2})?\s*[apAP](?:[mM])?|[Vv][Aa][Rr][Ii][Oo][Uu][Ss]))"  # 6: time slot (AM/PM optional on start, optional space before AM/PM)
    r"(?:\s+\d{1,2}(?::?\d{2})?(?:\s*[apAP](?:[mM])?)?-\d{1,2}(?::?\d{2})?\s*[apAP](?:[mM])?)?"  # optional duplicate time slot
    r"\s+(:\d{2}(?:/:\d{2})?)"                        # 7: spot length
    r"(?:\s+\$?([\d,]+(?:\.\d{2})?))?"               # 8: rate per spot (optional)
    r"(?:\s+CDR)?"                                    # optional PCode
    r"\s+([A-Z]{2,5})"                                # 9: rate type
    r"\s+(\d+)"                                       # 10: spots
    r"\s+\$?([\d,]+(?:\.\d{2})?)",                    # 11: line total
    re.MULTILINE,
)

_LINE_ITEM_PREFIX_RE = re.compile(r"^N\s+\d+\b", re.MULTILINE)

_WEEK_RE = re.compile(
    r"Week:\s+"
    r"(\d{2}/\d{2}/\d{2,4})"                         # start date
    r"\s+(\d{2}/\d{2}/\d{2,4})"                      # end date
    r"\s+([-1]{7})"                                   # day pattern
    r"\s+(\d+)"                                       # spots
    r"\s+\$?([\d,]+(?:\.\d{2})?)",                    # rate
)


def _parse_dollar(s: str) -> float:
    return float(s.replace(",", ""))


def parse_line_items(text: str) -> list[LineItem]:
    """Parse line items from contract text.

    Each line item follows the pattern:
    N <line#> <channel> <start> <end> <show> <time> <length> <rate> <type> <spots> <amount>
    """
    if not text or not text.strip():
        return []

    items: list[LineItem] = []
    for m in _LINE_ITEM_RE.finditer(text):
        items.append(LineItem(
            line_number=int(m.group(1)),
            channel=m.group(2),
            start_date=m.group(3),
            end_date=m.group(4),
            show_name=m.group(5).strip(),
            time_slot=m.group(6),
            spot_length=m.group(7),
            rate_per_spot=_parse_dollar(m.group(8)) if m.group(8) else None,
            rate_type=m.group(9),
            spots=int(m.group(10)),
            line_total=_parse_dollar(m.group(11)),
        ))
    return items


def count_line_item_candidates(text: str) -> int:
    """Count lines that look like line-item starts (near-miss detector)."""
    if not text or not text.strip():
        return 0
    return len(_LINE_ITEM_PREFIX_RE.findall(text))


def parse_week_breakdowns(text: str) -> list[dict]:
    """Parse week breakdown lines.

    Format: Week: MM/DD/YY MM/DD/YY -1111-- <spots> $<rate>
    Day pattern: 7 chars, '-' or '1' for Sun-Sat.
    """
    if not text or not text.strip():
        return []

    weeks: list[dict] = []
    for m in _WEEK_RE.finditer(text):
        weeks.append({
            "start_date": m.group(1),
            "end_date": m.group(2),
            "day_pattern": m.group(3),
            "spots": int(m.group(4)),
            "rate": _parse_dollar(m.group(5)),
        })
    return weeks
