"""Contract-level metadata extraction from FCC political ad PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ContractMeta:
    contract_number: str | None = None
    revision_number: int = 0
    agency: str | None = None
    demographic: str | None = None
    contract_start: str | None = None
    contract_end: str | None = None
    total_spots: int | None = None
    gross_total: float | None = None
    agency_commission: float | None = None
    net_total: float | None = None


def extract_contract_number(text: str) -> str | None:
    """Extract contract number from text.

    Handles formats:
      Contract: 424082
      Contract: 424082-New / 424082-Rev 1
      Contract #729823
      Contract: 729823--3
      TomSteyer_1474031_Rev1
    """
    # "Contract" label followed by number (with optional suffixes)
    m = re.search(r"(?i)contract\s*[:#]?\s*(\d{5,7})", text)
    if m:
        return m.group(1)

    # WideOrbit: standalone number followed by " / " (on its own line)
    m = re.search(r"(?m)^\s*(\d{5,7})\s*/\s*\w+", text)
    if m:
        return m.group(1)

    # Underscore-delimited: name_NUMBER_Rev
    m = re.search(r"_(\d{5,7})_", text)
    if m:
        return m.group(1)

    return None


def extract_revision(text: str) -> int:
    """Extract revision number from text. Returns 0 for originals/new."""
    # "Rev N" or "Rev. N" or "_Rev1" (case-insensitive)
    m = re.search(r"(?i)(?:^|[\s_-])rev\.?\s*(\d+)", text)
    if m:
        return int(m.group(1))

    # Double-hyphen style: 729823--3
    m = re.search(r"\d{5,7}--(\d+)", text)
    if m:
        return int(m.group(1))

    # "REVISION N"
    m = re.search(r"(?i)\brevision\s+(\d+)", text)
    if m:
        return int(m.group(1))

    # Explicit "New" or "Original" → revision 0
    # No marker at all → also revision 0
    return 0


def extract_contract_dates(text: str) -> tuple[str, str] | None:
    """Extract contract start and end dates.

    Returns (start_date, end_date) strings as they appear in the text.
    """
    date_pat = r"(\d{1,2}/\d{1,2}/\d{2,4})"
    # Labeled: "Contract Dates:" or "Contract Dates" followed by date range
    # Allow newlines + intervening text between label and dates (WideOrbit format)
    m = re.search(
        rf"(?i)contract\s+dates?\b.*?{date_pat}\s*[-–—]\s*{date_pat}",
        text,
        re.DOTALL,
    )
    if m:
        return m.group(1), m.group(2)

    return None


def extract_agency(text: str) -> str | None:
    """Extract agency name from 'Agency:' label."""
    m = re.search(r"(?i)agency\s*:\s*(.+)", text)
    if m:
        return m.group(1).strip()
    return None


def extract_demographics(text: str) -> str | None:
    """Extract demographic target from 'Demographic:' label."""
    m = re.search(r"(?i)demographic\s*:?\s*\n?\s*(.+)", text)
    if m:
        return m.group(1).strip()
    return None


def _parse_dollar(s: str) -> float:
    """Parse a dollar string like '$522,700.00' or '($78,405.00)' to float."""
    s = s.strip().replace("$", "").replace(",", "")
    s = s.strip("()")
    return float(s)


def extract_contract_totals(text: str) -> dict | None:
    """Extract contract-level totals from the summary block.

    Looks for:
      Totals  <spots>  $<gross>
    And optionally:
      Time Period  # Spots  Gross Amount  Agency Comm.  Net Amount
      02/23-03/09  227      $522,700.00   ($78,405.00)  $444,295.00
    """
    result: dict = {}

    # "Totals" line: spots and gross amount
    m = re.search(
        r"(?i)totals\s+(\d+)\s+(\$[\d,]+(?:\.\d{2})?)",
        text,
    )
    if not m:
        return None

    result["total_spots"] = int(m.group(1))
    result["gross_total"] = _parse_dollar(m.group(2))

    # Commission/net line: look for ($XX) pattern (commission in parens) and net after it
    m = re.search(
        r"(\$[\d,]+(?:\.\d{2})?)\s+\((\$[\d,]+(?:\.\d{2})?)\)\s+(\$[\d,]+(?:\.\d{2})?)",
        text,
    )
    if m:
        # gross_total from this line should match the totals line
        result["agency_commission"] = _parse_dollar(m.group(2))
        result["net_total"] = _parse_dollar(m.group(3))

    return result


def extract_contract_meta(text: str) -> ContractMeta:
    """Extract all contract-level metadata from the full document text."""
    meta = ContractMeta()

    meta.contract_number = extract_contract_number(text)
    meta.revision_number = extract_revision(text)
    meta.agency = extract_agency(text)
    meta.demographic = extract_demographics(text)

    dates = extract_contract_dates(text)
    if dates:
        meta.contract_start, meta.contract_end = dates

    totals = extract_contract_totals(text)
    if totals:
        meta.total_spots = totals.get("total_spots")
        meta.gross_total = totals.get("gross_total")
        meta.agency_commission = totals.get("agency_commission")
        meta.net_total = totals.get("net_total")

    return meta
