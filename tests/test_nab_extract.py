from fcc_ad_tracker.nab_extract import extract_nab_form


NAB_TEXT = """\
NAB FORM PB-18
Candidate Name: Tom Steyer
Office Sought: Governor
Party Affiliation: Democratic
State Office: Statewide
"""


def test_extract_nab_form_pb18():
    result = extract_nab_form(NAB_TEXT)
    assert result is not None
    assert result.form_type == "PB-18"
    assert result.candidate_name == "Tom Steyer"
    assert result.office_sought == "Governor"
    assert result.party_affiliation == "Democratic"
    assert result.election_level is not None


def test_extract_nab_form_non_nab_returns_none():
    assert extract_nab_form("Contract: 424082") is None
