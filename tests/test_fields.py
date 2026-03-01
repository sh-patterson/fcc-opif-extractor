from fcc_ca_ads.fields import (
    FieldMatch,
    extract_advertiser,
    extract_candidate,
    extract_total,
    extract_flight_dates,
    extract_all_fields,
)

SAMPLE_TEXT = """\
Political File
Advertiser: ACME PAC
Candidate: Jane Smith for Congress
Office: U.S. House of Representatives, District 45
Flight: 03/01/2026 - 03/15/2026
Gross Total: $15,000.00
"""


def test_extract_advertiser_labeled():
    matches = extract_advertiser(SAMPLE_TEXT)
    assert len(matches) >= 1
    best = matches[0]
    assert best.field_name == "advertiser"
    assert best.value == "ACME PAC"
    assert best.confidence == "high"


def test_extract_candidate_labeled():
    matches = extract_candidate(SAMPLE_TEXT)
    assert len(matches) >= 1
    best = matches[0]
    assert best.field_name == "candidate"
    assert best.value == "Jane Smith"
    assert best.confidence == "high"


def test_extract_total_labeled():
    matches = extract_total(SAMPLE_TEXT)
    assert len(matches) >= 1
    best = matches[0]
    assert best.field_name == "total"
    assert best.value == "$15,000.00"
    assert best.confidence == "high"


def test_extract_flight_dates():
    matches = extract_flight_dates(SAMPLE_TEXT)
    assert len(matches) >= 1
    best = matches[0]
    assert best.field_name == "flight_dates"
    assert "03/01/2026" in best.value
    assert "03/15/2026" in best.value


def test_extract_all_fields_returns_all():
    matches = extract_all_fields(SAMPLE_TEXT)
    field_names = {m.field_name for m in matches}
    assert "advertiser" in field_names
    assert "candidate" in field_names
    assert "total" in field_names
    assert "flight_dates" in field_names


def test_extract_all_fields_empty_input():
    assert extract_all_fields("") == []
    assert extract_all_fields("   ") == []
    assert extract_all_fields("\n\n") == []


def test_all_matches_have_valid_confidence():
    matches = extract_all_fields(SAMPLE_TEXT)
    for m in matches:
        assert m.confidence in ("high", "medium", "low")


def test_extract_all_fields_best_per_field():
    """extract_all_fields returns at most one match per field name."""
    matches = extract_all_fields(SAMPLE_TEXT)
    field_names = [m.field_name for m in matches]
    assert len(field_names) == len(set(field_names))


def test_page_number_propagated():
    matches = extract_advertiser(SAMPLE_TEXT, page=3)
    assert matches[0].page_number == 3


def test_extract_candidate_contextual():
    """'for Congress' pattern gives medium confidence for candidate."""
    text = "Paid for by Jane Smith for Congress"
    matches = extract_candidate(text)
    assert len(matches) >= 1
    assert matches[0].value == "Jane Smith"
    assert matches[0].confidence == "medium"


def test_extract_advertiser_ordered_by():
    """'Ordered By' label gives medium confidence for advertiser."""
    text = "Ordered By: Citizens United PAC"
    matches = extract_advertiser(text)
    assert len(matches) >= 1
    assert matches[0].value == "Citizens United PAC"
    assert matches[0].confidence == "medium"


def test_extract_total_bare_amount():
    """Bare dollar amount >= $1000 with no label gives low confidence."""
    text = "Some unrelated text\n$25,000.00\nMore text"
    matches = extract_total(text)
    assert len(matches) >= 1
    low_matches = [m for m in matches if m.confidence == "low"]
    assert len(low_matches) >= 1
    assert low_matches[0].value == "$25,000.00"


def test_extract_total_ignores_small_amounts():
    """Bare dollar amounts under $1000 should not match as low confidence."""
    text = "Cost per spot: $50.00"
    matches = extract_total(text)
    # Should not pick up $50 as a total
    assert len(matches) == 0


def test_fieldmatch_dataclass():
    m = FieldMatch(field_name="test", value="val", confidence="high", page_number=1)
    assert m.field_name == "test"
    assert m.value == "val"
    assert m.confidence == "high"
    assert m.page_number == 1


def test_fieldmatch_default_page():
    m = FieldMatch(field_name="test", value="val", confidence="high")
    assert m.page_number == 0
