"""Tests for Gemini Flash extraction fallback."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from fcc_ad_tracker.gemini_extract import (
    GeminiContractMeta,
    GeminiExtractionResult,
    GeminiLineItem,
    build_prompt,
    gemini_extract,
    gemini_result_to_contract_meta,
    gemini_result_to_line_items,
)
from fcc_ad_tracker.contracts import ContractMeta
from fcc_ad_tracker.line_items import LineItem


SAMPLE_GEMINI_RESPONSE = {
    "contract": {
        "contract_number": "424082",
        "advertiser": "TOM STEYER FOR GOVERNOR 2026",
        "candidate": "Tom Steyer",
        "agency": "BUYER'S EDGE MEDIA LLC",
        "demographic": "A25-54",
        "contract_start": "02/23/2026",
        "contract_end": "03/09/2026",
    },
    "line_items": [
        {
            "line_number": 58,
            "channel": "KABC",
            "start_date": "03/03/26",
            "end_date": "03/08/26",
            "show_name": "NBA LA Lakers",
            "time_slot": "various",
            "spot_length": ":30",
            "rate_per_spot": 25000.0,
            "rate_type": "NM",
            "spots": 1,
            "line_total": 25000.0,
        },
        {
            "line_number": 59,
            "channel": "KABC",
            "start_date": "03/03/26",
            "end_date": "03/07/26",
            "show_name": "5A News",
            "time_slot": "5:00A-5:30A",
            "spot_length": ":30",
            "rate_per_spot": 500.0,
            "rate_type": "NM",
            "spots": 5,
            "line_total": 2500.0,
        },
    ],
}


class TestPydanticModels:
    def test_line_item_required_fields_only(self):
        item = GeminiLineItem(
            line_number=1,
            channel="KABC",
            start_date="03/03/26",
            end_date="03/07/26",
            show_name="Test Show",
            spot_length=":30",
            spots=5,
            line_total=5000.0,
        )
        assert item.line_number == 1
        assert item.time_slot is None
        assert item.rate_per_spot is None
        assert item.rate_type is None

    def test_line_item_all_fields(self):
        item = GeminiLineItem(**SAMPLE_GEMINI_RESPONSE["line_items"][0])
        assert item.line_number == 58
        assert item.time_slot == "various"
        assert item.rate_per_spot == 25000.0
        assert item.rate_type == "NM"

    def test_contract_meta_all_optional(self):
        meta = GeminiContractMeta()
        assert meta.contract_number is None
        assert meta.advertiser is None
        assert meta.agency is None

    def test_contract_meta_full(self):
        meta = GeminiContractMeta(**SAMPLE_GEMINI_RESPONSE["contract"])
        assert meta.contract_number == "424082"
        assert meta.agency == "BUYER'S EDGE MEDIA LLC"
        assert meta.demographic == "A25-54"

    def test_extraction_result_from_dict(self):
        result = GeminiExtractionResult(**SAMPLE_GEMINI_RESPONSE)
        assert result.contract.contract_number == "424082"
        assert len(result.line_items) == 2
        assert result.line_items[0].show_name == "NBA LA Lakers"

    def test_extraction_result_from_json(self):
        result = GeminiExtractionResult.model_validate_json(
            json.dumps(SAMPLE_GEMINI_RESPONSE)
        )
        assert result.contract.contract_number == "424082"
        assert len(result.line_items) == 2


class TestBuildPrompt:
    def test_includes_page_content(self):
        prompt = build_prompt(["Page 1 content here"])
        assert "Page 1 content here" in prompt

    def test_includes_grounding_instruction(self):
        prompt = build_prompt(["anything"])
        assert "Extract ONLY" in prompt
        assert "Do not infer or fabricate" in prompt

    def test_joins_multiple_pages(self):
        prompt = build_prompt(["Page 1", "Page 2", "Page 3"])
        assert "Page 1" in prompt
        assert "Page 2" in prompt
        assert "Page 3" in prompt

    def test_empty_pages(self):
        prompt = build_prompt([])
        assert "Extract ONLY" in prompt


class TestResultConversion:
    def test_to_contract_meta(self):
        result = GeminiExtractionResult(**SAMPLE_GEMINI_RESPONSE)
        meta = gemini_result_to_contract_meta(result)
        assert isinstance(meta, ContractMeta)
        assert meta.contract_number == "424082"
        assert meta.agency == "BUYER'S EDGE MEDIA LLC"
        assert meta.demographic == "A25-54"
        assert meta.contract_start == "02/23/2026"
        assert meta.contract_end == "03/09/2026"

    def test_to_contract_meta_preserves_defaults(self):
        result = GeminiExtractionResult(
            contract=GeminiContractMeta(),
            line_items=[],
        )
        meta = gemini_result_to_contract_meta(result)
        assert meta.contract_number is None
        assert meta.revision_number == 0
        assert meta.gross_total is None

    def test_to_line_items(self):
        result = GeminiExtractionResult(**SAMPLE_GEMINI_RESPONSE)
        items = gemini_result_to_line_items(result)
        assert len(items) == 2
        assert all(isinstance(i, LineItem) for i in items)

        lakers = items[0]
        assert lakers.line_number == 58
        assert lakers.channel == "KABC"
        assert lakers.show_name == "NBA LA Lakers"
        assert lakers.time_slot == "various"
        assert lakers.spot_length == ":30"
        assert lakers.rate_per_spot == 25000.0
        assert lakers.rate_type == "NM"
        assert lakers.spots == 1
        assert lakers.line_total == 25000.0

    def test_to_line_items_none_defaults_to_empty_string(self):
        result = GeminiExtractionResult(
            contract=GeminiContractMeta(),
            line_items=[
                GeminiLineItem(
                    line_number=1,
                    channel="KABC",
                    start_date="03/03/26",
                    end_date="03/07/26",
                    show_name="Test",
                    spot_length=":30",
                    spots=1,
                    line_total=100.0,
                )
            ],
        )
        items = gemini_result_to_line_items(result)
        assert items[0].time_slot == ""
        assert items[0].rate_type == ""
        assert items[0].rate_per_spot is None

    def test_to_line_items_empty(self):
        result = GeminiExtractionResult(
            contract=GeminiContractMeta(),
            line_items=[],
        )
        assert gemini_result_to_line_items(result) == []


class TestGeminiExtract:
    def test_returns_none_without_api_key(self):
        env = os.environ.copy()
        env.pop("GOOGLE_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = gemini_extract(["some text"])
            assert result is None

    @patch("fcc_ad_tracker.gemini_extract.genai_types")
    @patch("fcc_ad_tracker.gemini_extract.genai")
    def test_successful_extraction(self, mock_genai, mock_genai_types):
        mock_response = MagicMock()
        mock_response.text = json.dumps(SAMPLE_GEMINI_RESPONSE)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.Client.return_value = mock_client

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            result = gemini_extract(["Contract: 424082\nAdvertiser: TEST"])

        assert result is not None
        assert result.contract.contract_number == "424082"
        assert len(result.line_items) == 2
        mock_genai.Client.assert_called_once_with(api_key="test-key")

    @patch("fcc_ad_tracker.gemini_extract.genai_types")
    @patch("fcc_ad_tracker.gemini_extract.genai")
    def test_uses_correct_model(self, mock_genai, mock_genai_types):
        mock_response = MagicMock()
        mock_response.text = json.dumps(SAMPLE_GEMINI_RESPONSE)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.Client.return_value = mock_client

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            gemini_extract(["text"])

        call_kwargs = mock_client.models.generate_content.call_args
        assert call_kwargs.kwargs["model"] == "gemini-3-flash-preview"

    @patch("fcc_ad_tracker.gemini_extract.genai_types")
    @patch("fcc_ad_tracker.gemini_extract.genai")
    def test_api_error_returns_none(self, mock_genai, mock_genai_types):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API Error")
        mock_genai.Client.return_value = mock_client

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            result = gemini_extract(["some text"])

        assert result is None

    def test_returns_none_without_genai_package(self):
        with patch("fcc_ad_tracker.gemini_extract.genai", None):
            with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
                result = gemini_extract(["some text"])
                assert result is None


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set",
)
class TestGeminiExtractIntegration:
    def test_real_extraction(self):
        """Feed real contract text to Gemini and verify structured output."""
        pages = [
            "Contract Agreement Between\n"
            "Contract: 424082                          Estimate: 31879\n"
            "Advertiser: TOM STEYER FOR GOVERNOR 2026\n"
            "Product: Political\n"
            "Agency: BUYER'S EDGE MEDIA LLC\n"
            "Demographic: A25-54\n"
            "Contract Dates: 02/23/2026 - 03/09/2026\n"
            "\n"
            "N 58    KABC     03/03/26  03/08/26   NBA LA Lakers"
            "     various     :30    $25,000   NM     1      $25,000\n"
            "N 59    KABC     03/03/26  03/07/26   5A News"
            "           5:00A-5:30A :30    $500      NM     5      $2,500\n"
        ]
        result = gemini_extract(pages)
        assert result is not None
        assert result.contract.contract_number is not None
        assert len(result.line_items) > 0
