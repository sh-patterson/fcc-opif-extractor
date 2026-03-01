from pathlib import Path

import pytest
from fpdf import FPDF


@pytest.fixture
def text_pdf(tmp_path) -> Path:
    """A PDF with extractable text containing political ad data."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(text="Advertiser: ACME PAC")
    pdf.ln()
    pdf.cell(text="Candidate: Jane Smith")
    pdf.ln()
    pdf.cell(text="Total: $15,000.00")
    pdf.ln()
    pdf.cell(text="Flight: 03/01/2026 - 03/15/2026")
    out = tmp_path / "text.pdf"
    pdf.output(str(out))
    return out


@pytest.fixture
def empty_text_pdf(tmp_path) -> Path:
    """A PDF with no meaningful text (whitespace only)."""
    pdf = FPDF()
    pdf.add_page()
    # Add only whitespace — no real content
    pdf.set_font("Helvetica", size=12)
    pdf.cell(text="   ")
    out = tmp_path / "empty.pdf"
    pdf.output(str(out))
    return out
