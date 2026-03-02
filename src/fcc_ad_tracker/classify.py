"""File type classification and contract number parsing from filenames/paths."""

from __future__ import annotations

import re


def classify_file_type(file_name: str, folder_path: str = "", page0_text: str = "") -> str:
    """Classify a file as contract, invoice, nab, traffic, or unknown.

    Uses filename, folder path, and optionally page 0 text content.
    """
    name_lower = file_name.lower()
    path_lower = folder_path.lower()

    # NAB forms
    if "nab" in name_lower:
        return "nab"

    # Traffic instructions
    if "traffic" in name_lower or "traffic" in path_lower:
        return "traffic"

    # Invoices
    if "invoice" in name_lower:
        return "invoice"

    # Content-based detection
    if page0_text:
        text_lower = page0_text.lower()
        if "contract agreement" in text_lower or "contract:" in text_lower:
            return "contract"
        if "invoice" in text_lower and "amount due" in text_lower:
            return "invoice"
        if "nab form" in text_lower or "national association of broadcasters" in text_lower:
            return "nab"

    # If it has a contract-like filename pattern, classify as contract
    if re.search(r"\d{5,7}", name_lower):
        return "contract"

    return "unknown"


def parse_contract_number_from_filename(file_name: str) -> str | None:
    """Extract contract number from filename patterns.

    Handles:
      424082-New.pdf / 424082-Rev 1.pdf
      729823--1.pdf
      TomSteyer_1474031_Rev1.pdf
    """
    # Standard: digits possibly followed by -New, -Rev, --N
    m = re.search(r"(\d{5,7})(?:-|_|\.)", file_name)
    if m:
        return m.group(1)

    # Underscore-delimited
    m = re.search(r"_(\d{5,7})_", file_name)
    if m:
        return m.group(1)

    return None


def is_terms_and_conditions(page_text: str) -> bool:
    """Check if a page is a Terms & Conditions page that should be skipped."""
    if not page_text or not page_text.strip():
        return False
    # Check first 200 chars for T&C markers
    header = page_text[:200].upper()
    return (
        "TERMS AND CONDITIONS" in header
        or "TERMS & CONDITIONS" in header
        or "STANDARD TERMS" in header
    )


def parse_revision_from_filename(file_name: str) -> int:
    """Extract revision number from filename. Returns 0 for originals."""
    # "Rev N" or "Rev.N" or "RevN"
    m = re.search(r"(?i)rev\.?\s*(\d+)", file_name)
    if m:
        return int(m.group(1))

    # Double-hyphen: 729823--3
    m = re.search(r"\d{5,7}--(\d+)", file_name)
    if m:
        return int(m.group(1))

    # "New" suffix → revision 0
    if re.search(r"(?i)-new\b", file_name):
        return 0

    # "REVISION N"
    m = re.search(r"(?i)revision\s*(\d+)", file_name)
    if m:
        return int(m.group(1))

    return 0
