from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which

import pdfplumber

TEXT_THRESHOLD = 20  # min chars to consider "has text"


@dataclass
class ExtractionResult:
    has_text: bool
    ocr_used: bool
    pages: list[str] = field(default_factory=list)
    error: str | None = None


def has_text_layer(pdf_path: Path) -> bool:
    """Check whether the PDF has enough extractable text."""
    pages = extract_text_pages(pdf_path)
    total = sum(len(p.strip()) for p in pages)
    return total >= TEXT_THRESHOLD


def extract_text_pages(pdf_path: Path) -> list[str]:
    """Extract text from each page using pdfplumber."""
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return pages


def ocr_pdf(pdf_path: Path, output_path: Path) -> Path:
    """Run OCR on a PDF using ocrmypdf. Returns path to OCR'd PDF."""
    if which("ocrmypdf") is None:
        raise RuntimeError("ocrmypdf is not installed")
    subprocess.run(
        ["ocrmypdf", "--skip-text", str(pdf_path), str(output_path)],
        check=True,
        capture_output=True,
    )
    return output_path


def extract_pdf_text(pdf_path: Path) -> ExtractionResult:
    """Main entry point: extract text from PDF, falling back to OCR if needed."""
    pages = extract_text_pages(pdf_path)
    total_chars = sum(len(p.strip()) for p in pages)

    if total_chars >= TEXT_THRESHOLD:
        return ExtractionResult(has_text=True, ocr_used=False, pages=pages)

    # Try OCR fallback
    try:
        ocr_output = pdf_path.with_name(pdf_path.stem + "_ocr.pdf")
        ocr_pdf(pdf_path, ocr_output)
        ocr_pages = extract_text_pages(ocr_output)
        ocr_chars = sum(len(p.strip()) for p in ocr_pages)
        return ExtractionResult(
            has_text=ocr_chars >= TEXT_THRESHOLD,
            ocr_used=True,
            pages=ocr_pages,
        )
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        return ExtractionResult(
            has_text=False,
            ocr_used=False,
            pages=pages,
            error=str(exc),
        )
