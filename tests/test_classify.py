"""Tests for file type classification and filename parsing."""

from fcc_ad_tracker.classify import (
    classify_file_type,
    parse_contract_number_from_filename,
    parse_revision_from_filename,
    is_terms_and_conditions,
)


class TestClassifyFileType:
    def test_nab_in_filename(self):
        assert classify_file_type("NAB_Form_PB-18.pdf") == "nab"

    def test_traffic_in_filename(self):
        assert classify_file_type("traffic_instructions.pdf") == "traffic"

    def test_traffic_in_folder(self):
        assert classify_file_type("order.pdf", folder_path="/Political Files/Traffic/2026") == "traffic"

    def test_invoice_in_filename(self):
        assert classify_file_type("Invoice_March2026.pdf") == "invoice"

    def test_contract_by_content(self):
        assert classify_file_type(
            "424082.pdf", page0_text="Contract Agreement Between\nContract: 424082"
        ) == "contract"

    def test_contract_by_number_pattern(self):
        assert classify_file_type("424082-New.pdf") == "contract"

    def test_unknown(self):
        assert classify_file_type("misc.pdf") == "unknown"

    def test_invoice_by_content(self):
        assert classify_file_type(
            "bill.pdf", page0_text="Invoice\nAmount Due: $5,000"
        ) == "invoice"


class TestIsTermsAndConditions:
    def test_tc_header(self):
        assert is_terms_and_conditions("TERMS AND CONDITIONS\n1. The station agrees...") is True

    def test_tc_ampersand(self):
        assert is_terms_and_conditions("TERMS & CONDITIONS\nAll orders...") is True

    def test_standard_terms(self):
        assert is_terms_and_conditions("STANDARD TERMS\nThis agreement...") is True

    def test_contract_page(self):
        assert is_terms_and_conditions("Contract: 424082\nAdvertiser: ACME") is False

    def test_empty_page(self):
        assert is_terms_and_conditions("") is False

    def test_tc_not_at_start(self):
        """T&C buried in middle of page should NOT trigger skip."""
        text = "Line items here\n" * 20 + "TERMS AND CONDITIONS"
        assert is_terms_and_conditions(text) is False


class TestParseContractNumberFromFilename:
    def test_standard(self):
        assert parse_contract_number_from_filename("424082-New.pdf") == "424082"

    def test_with_rev(self):
        assert parse_contract_number_from_filename("424082-Rev 1.pdf") == "424082"

    def test_double_hyphen(self):
        assert parse_contract_number_from_filename("729823--1.pdf") == "729823"

    def test_underscore(self):
        assert parse_contract_number_from_filename("TomSteyer_1474031_Rev1.pdf") == "1474031"

    def test_no_number(self):
        assert parse_contract_number_from_filename("order.pdf") is None

    def test_short_number_ignored(self):
        assert parse_contract_number_from_filename("ad-123.pdf") is None


class TestParseRevisionFromFilename:
    def test_new_is_zero(self):
        assert parse_revision_from_filename("424082-New.pdf") == 0

    def test_rev_1(self):
        assert parse_revision_from_filename("424082-Rev 1.pdf") == 1

    def test_rev_2(self):
        assert parse_revision_from_filename("424082-Rev 2.pdf") == 2

    def test_double_hyphen(self):
        assert parse_revision_from_filename("729823--3.pdf") == 3

    def test_underscore_rev(self):
        assert parse_revision_from_filename("TomSteyer_1474031_Rev1.pdf") == 1

    def test_revision_word(self):
        assert parse_revision_from_filename("REVISION2.pdf") == 2

    def test_no_revision(self):
        assert parse_revision_from_filename("424082.pdf") == 0
