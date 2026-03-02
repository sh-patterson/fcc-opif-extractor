"""Gemini Flash structured extraction fallback for FCC contract PDFs."""

from __future__ import annotations

import logging
import os

from pydantic import BaseModel

from fcc_ad_tracker.contracts import ContractMeta
from fcc_ad_tracker.line_items import LineItem

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]


class GeminiLineItem(BaseModel):
    line_number: int
    channel: str
    start_date: str
    end_date: str
    show_name: str
    time_slot: str | None = None
    spot_length: str
    rate_per_spot: float | None = None
    rate_type: str | None = None
    spots: int
    line_total: float


class GeminiContractMeta(BaseModel):
    contract_number: str | None = None
    advertiser: str | None = None
    candidate: str | None = None
    agency: str | None = None
    demographic: str | None = None
    contract_start: str | None = None
    contract_end: str | None = None


class GeminiExtractionResult(BaseModel):
    contract: GeminiContractMeta
    line_items: list[GeminiLineItem]


_EXTRACTION_PROMPT = """\
Extract contract metadata and line items from this FCC political ad contract text.

Extract ONLY information that is explicitly present in the text. Do not infer or fabricate values.

Field definitions:
- contract_number: The 5-7 digit contract/order number
- advertiser: The advertising entity (often a committee name)
- candidate: The candidate name if identified
- agency: The media buying agency
- demographic: Target demographic (e.g., "A25-54", "HH", "Adults 35+")
- contract_start / contract_end: Contract flight dates in MM/DD/YY or MM/DD/YYYY format
- line_number: The line item number (after "N" marker)
- channel: Station call sign (e.g., KABC, KCBS)
- start_date / end_date: Air dates for this line item
- show_name: Program name
- time_slot: Time period (e.g., "5:00A-5:30A", "4p-5p", "various")
- spot_length: Duration of spot (e.g., ":30", ":15", ":15/:15")
- rate_per_spot: Dollar amount per spot (null if not listed)
- rate_type: Rate classification ("NM", "BK", "CDR", or null if not identified)
- spots: Number of spots
- line_total: Total dollar amount for this line

Contract text:
"""


def build_prompt(pages: list[str]) -> str:
    """Build the extraction prompt from page texts."""
    return _EXTRACTION_PROMPT + "\n".join(pages)


def gemini_result_to_contract_meta(result: GeminiExtractionResult) -> ContractMeta:
    """Convert Gemini extraction result to ContractMeta dataclass."""
    c = result.contract
    return ContractMeta(
        contract_number=c.contract_number,
        agency=c.agency,
        demographic=c.demographic,
        contract_start=c.contract_start,
        contract_end=c.contract_end,
    )


def gemini_result_to_line_items(result: GeminiExtractionResult) -> list[LineItem]:
    """Convert Gemini line items to LineItem dataclasses."""
    return [
        LineItem(
            line_number=gli.line_number,
            channel=gli.channel,
            start_date=gli.start_date,
            end_date=gli.end_date,
            show_name=gli.show_name,
            time_slot=gli.time_slot or "",
            spot_length=gli.spot_length,
            rate_per_spot=gli.rate_per_spot,
            rate_type=gli.rate_type or "",
            spots=gli.spots,
            line_total=gli.line_total,
        )
        for gli in result.line_items
    ]


def gemini_extract(pages: list[str]) -> GeminiExtractionResult | None:
    """Extract contract data using Gemini Flash.

    Returns parsed GeminiExtractionResult or None on errors.
    Requires GOOGLE_API_KEY environment variable and google-genai package.
    """
    if genai is None:
        logger.warning("google-genai not installed, skipping Gemini extraction")
        return None

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("GOOGLE_API_KEY not set, skipping Gemini extraction")
        return None

    try:
        client = genai.Client(api_key=api_key)
        prompt = build_prompt(pages)
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiExtractionResult,
            ),
        )
        return GeminiExtractionResult.model_validate_json(response.text)
    except Exception:
        logger.exception("Gemini extraction failed")
        return None
