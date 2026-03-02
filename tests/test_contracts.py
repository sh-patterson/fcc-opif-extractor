"""Tests for contract-level metadata extraction."""

from fcc_ad_tracker.contracts import (
    ContractMeta,
    extract_contract_number,
    extract_revision,
    extract_contract_dates,
    extract_agency,
    extract_demographics,
    extract_contract_totals,
    extract_contract_meta,
)


# Realistic contract header text (page 0) based on actual FCC filings
HEADER_TEXT = """\
Contract Agreement Between
Contract: 424082                          Estimate: 31879
Advertiser: TOM STEYER FOR GOVERNOR 2026
Product: Political
Agency: BUYER'S EDGE MEDIA LLC
       1234 K STREET NW SUITE 400
       WASHINGTON DC 20005
Billing Cycle: Weekly
Demographic: A25-54
Contract Dates: 02/23/2026 - 03/09/2026
"""

HEADER_TEXT_ALT = """\
Contract #729823                          Rev 2
Advertiser: CITIZENS FOR GOOD GOVERNMENT
Product: Political Advertising
Agency: MENTZER MEDIA SERVICES
Demographic: HH
Contract Dates  03/01/26 - 03/15/26
"""

# Summary block text (typically last content page)
SUMMARY_TEXT = """\
Program                    Spots    Amount
5A News                      14    $7,000.00
Good Morning America         28    $84,000.00
NBA LA Lakers                 1    $25,000.00
Totals                      227    $522,700.00

Time Period    # Spots  Gross Amount    Agency Comm.     Net Amount
02/23-03/09    227      $522,700.00     ($78,405.00)     $444,295.00
"""

SUMMARY_TEXT_NO_COMMISSION = """\
Totals                       45    $135,000.00
"""

# WideOrbit format — contract number on separate line from label
WIDEORBIT_HEADER = """\
Contract / Revision Alt Order #
KABC
424880 / WOC15574999
Advertiser: TOM STEYER FOR GOVERNOR 2026
Agency: BUYER'S EDGE MEDIA LLC
Contract Dates Estimate # Ext. Opp. ID
05/25/26 - 06/07/26
Demographic
Adults 35+
"""

REVISION_TEXTS = {
    "original": "Contract: 424082-New",
    "rev1": "Contract: 424082-Rev 1",
    "rev2": "Contract: 424082-Rev 2",
    "double_hyphen": "Contract: 729823--3",
    "underscore_rev": "TomSteyer_1474031_Rev1",
    "word_original": "ORIGINAL ORDER",
    "word_revision": "REVISION 2",
    "no_marker": "Contract: 424082",
}


class TestExtractContractNumber:
    def test_standard_contract_number(self):
        result = extract_contract_number(HEADER_TEXT)
        assert result == "424082"

    def test_contract_with_hash(self):
        result = extract_contract_number(HEADER_TEXT_ALT)
        assert result == "729823"

    def test_contract_with_new_suffix(self):
        result = extract_contract_number("Contract: 424082-New")
        assert result == "424082"

    def test_contract_with_rev_suffix(self):
        result = extract_contract_number("Contract: 424082-Rev 1")
        assert result == "424082"

    def test_contract_double_hyphen(self):
        result = extract_contract_number("Contract: 729823--3")
        assert result == "729823"

    def test_underscore_style(self):
        result = extract_contract_number("TomSteyer_1474031_Rev1")
        assert result == "1474031"

    def test_wideorbit_number_on_separate_line(self):
        result = extract_contract_number(WIDEORBIT_HEADER)
        assert result == "424880"

    def test_no_contract_number(self):
        result = extract_contract_number("Some random text with no contract")
        assert result is None

    def test_ignores_short_numbers(self):
        """Numbers under 5 digits shouldn't match as contract numbers."""
        result = extract_contract_number("Contract: 123")
        assert result is None


class TestExtractRevision:
    def test_new_is_zero(self):
        assert extract_revision("Contract: 424082-New") == 0

    def test_original_is_zero(self):
        assert extract_revision("ORIGINAL ORDER") == 0

    def test_rev_1(self):
        assert extract_revision("Contract: 424082-Rev 1") == 1

    def test_rev_2(self):
        assert extract_revision("Contract: 424082-Rev 2") == 2

    def test_double_hyphen_revision(self):
        assert extract_revision("Contract: 729823--3") == 3

    def test_underscore_rev(self):
        assert extract_revision("TomSteyer_1474031_Rev1") == 1

    def test_revision_word(self):
        assert extract_revision("REVISION 2") == 2

    def test_no_revision_marker(self):
        assert extract_revision("Contract: 424082") == 0

    def test_rev_case_insensitive(self):
        assert extract_revision("rev 3") == 3


class TestExtractContractDates:
    def test_labeled_with_colon(self):
        start, end = extract_contract_dates(HEADER_TEXT)
        assert start == "02/23/2026"
        assert end == "03/09/2026"

    def test_labeled_without_colon(self):
        start, end = extract_contract_dates(HEADER_TEXT_ALT)
        assert start == "03/01/26"
        assert end == "03/15/26"

    def test_wideorbit_dates_on_separate_line(self):
        result = extract_contract_dates(WIDEORBIT_HEADER)
        assert result is not None
        start, end = result
        assert start == "05/25/26"
        assert end == "06/07/26"

    def test_no_dates(self):
        result = extract_contract_dates("No dates here")
        assert result is None


class TestExtractAgency:
    def test_labeled_agency(self):
        result = extract_agency(HEADER_TEXT)
        assert result == "BUYER'S EDGE MEDIA LLC"

    def test_alt_agency(self):
        result = extract_agency(HEADER_TEXT_ALT)
        assert result == "MENTZER MEDIA SERVICES"

    def test_no_agency(self):
        result = extract_agency("Some text without agency info")
        assert result is None


class TestExtractDemographics:
    def test_demographic_label(self):
        result = extract_demographics(HEADER_TEXT)
        assert result == "A25-54"

    def test_hh_demographic(self):
        result = extract_demographics(HEADER_TEXT_ALT)
        assert result == "HH"

    def test_wideorbit_demographic_on_separate_line(self):
        result = extract_demographics(WIDEORBIT_HEADER)
        assert result == "Adults 35+"

    def test_no_demographic(self):
        result = extract_demographics("No demo here")
        assert result is None


class TestExtractContractTotals:
    def test_full_summary(self):
        totals = extract_contract_totals(SUMMARY_TEXT)
        assert totals is not None
        assert totals["total_spots"] == 227
        assert totals["gross_total"] == 522700.00
        assert totals["agency_commission"] == 78405.00
        assert totals["net_total"] == 444295.00

    def test_totals_only(self):
        totals = extract_contract_totals(SUMMARY_TEXT_NO_COMMISSION)
        assert totals is not None
        assert totals["total_spots"] == 45
        assert totals["gross_total"] == 135000.00

    def test_no_totals(self):
        result = extract_contract_totals("No totals here")
        assert result is None


class TestExtractContractMeta:
    def test_full_extraction(self):
        full_text = HEADER_TEXT + "\n" + SUMMARY_TEXT
        meta = extract_contract_meta(full_text)
        assert isinstance(meta, ContractMeta)
        assert meta.contract_number == "424082"
        assert meta.revision_number == 0
        assert meta.agency == "BUYER'S EDGE MEDIA LLC"
        assert meta.demographic == "A25-54"
        assert meta.contract_start == "02/23/2026"
        assert meta.contract_end == "03/09/2026"
        assert meta.total_spots == 227
        assert meta.gross_total == 522700.00
        assert meta.agency_commission == 78405.00
        assert meta.net_total == 444295.00

    def test_partial_extraction(self):
        """Should still return a ContractMeta even if some fields are missing."""
        meta = extract_contract_meta(HEADER_TEXT)
        assert meta.contract_number == "424082"
        assert meta.agency == "BUYER'S EDGE MEDIA LLC"
        # Totals come from summary block, not header
        assert meta.gross_total is None

    def test_empty_text(self):
        meta = extract_contract_meta("")
        assert meta.contract_number is None

    def test_revision_detected(self):
        meta = extract_contract_meta("Contract: 424082-Rev 2\nAdvertiser: TEST")
        assert meta.contract_number == "424082"
        assert meta.revision_number == 2
