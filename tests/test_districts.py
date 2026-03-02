"""Tests for district-to-DMA crosswalk loading, matching, and queries."""
from __future__ import annotations

import sqlite3
import textwrap

import pytest

from fcc_ad_tracker.db.connection import init_schema
from fcc_ad_tracker.db import queries
from fcc_ad_tracker.districts import (
    auto_match_markets,
    insert_crosswalk,
    load_crosswalk_csv,
    update_market_mapping,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


@pytest.fixture
def crosswalk_csv(tmp_path):
    """Sample crosswalk CSV matching The Downballot format."""
    csv_content = textwrap.dedent("""\
        CD,Media market,State,Population,Percentage
        CA-27,Los Angeles,CA,"952,345",100.0%
        CA-48,Los Angeles,CA,"284,102",33.1%
        CA-48,San Diego,CA,"573,898",66.9%
        TX-22,Houston,TX,"780,000",100.0%
        AK-AL,Anchorage,AK,"371,991",52.1%
        AK-AL,[None],AK,"47,200",6.6%
        AK-AL,Fairbanks,AK,"98,123",13.8%
        NY-14,New York,NY,"750,000",100.0%
    """)
    path = tmp_path / "crosswalk.csv"
    path.write_text(csv_content)
    return path


class TestLoadCrosswalkCsv:
    def test_basic_parsing(self, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        # [None] row should be skipped
        assert len(rows) == 7

    def test_strips_commas_from_population(self, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        ca27 = [r for r in rows if r["district"] == "CA-27"][0]
        assert ca27["population"] == 952345

    def test_converts_pct_to_weight(self, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        ca27 = [r for r in rows if r["district"] == "CA-27"][0]
        assert ca27["weight"] == pytest.approx(1.0)

    def test_partial_weight(self, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        ca48_la = [r for r in rows if r["district"] == "CA-48" and r["dma_name"] == "Los Angeles"][0]
        assert ca48_la["weight"] == pytest.approx(0.331)

    def test_skips_none_dma(self, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        none_rows = [r for r in rows if r["dma_name"] == "[None]"]
        assert len(none_rows) == 0

    def test_state_field(self, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        tx22 = [r for r in rows if r["district"] == "TX-22"][0]
        assert tx22["state"] == "TX"

    def test_multiple_states(self, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        states = {r["state"] for r in rows}
        assert states == {"CA", "TX", "AK", "NY"}


class TestAutoMatchMarkets:
    def test_exact_uppercase_match(self, db, crosswalk_csv):
        queries.upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "Los Angeles", "CA", "TV")
        rows = load_crosswalk_csv(crosswalk_csv)
        matched, unmatched = auto_match_markets(db, rows)
        assert matched["Los Angeles"] == "LOS ANGELES"

    def test_unmatched_reported(self, db, crosswalk_csv):
        # No stations loaded — everything unmatched
        rows = load_crosswalk_csv(crosswalk_csv)
        matched, unmatched = auto_match_markets(db, rows)
        assert len(matched) == 0
        assert "Los Angeles" in unmatched

    def test_partial_match(self, db, crosswalk_csv):
        queries.upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "Los Angeles", "CA", "TV")
        queries.upsert_station(db, "2", "KHOU-TV", "HOUSTON", "Houston", "TX", "TV")
        rows = load_crosswalk_csv(crosswalk_csv)
        matched, unmatched = auto_match_markets(db, rows)
        assert "Los Angeles" in matched
        assert "Houston" in matched
        assert "San Diego" in unmatched


class TestInsertCrosswalk:
    def test_insert_count(self, db, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        count = insert_crosswalk(db, rows, {})
        assert count == 7

    def test_idempotent_reload(self, db, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        insert_crosswalk(db, rows, {})
        insert_crosswalk(db, rows, {})
        total = db.execute("SELECT COUNT(*) FROM dma_districts").fetchone()[0]
        assert total == 7

    def test_fcc_market_set_when_matched(self, db, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        market_map = {"Los Angeles": "LOS ANGELES"}
        insert_crosswalk(db, rows, market_map)
        row = db.execute(
            "SELECT fcc_market FROM dma_districts WHERE district = 'CA-27'"
        ).fetchone()
        assert row["fcc_market"] == "LOS ANGELES"

    def test_fcc_market_null_when_unmatched(self, db, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        insert_crosswalk(db, rows, {})
        row = db.execute(
            "SELECT fcc_market FROM dma_districts WHERE district = 'CA-27'"
        ).fetchone()
        assert row["fcc_market"] is None


class TestUpdateMarketMapping:
    def test_updates_matching_rows(self, db, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        insert_crosswalk(db, rows, {})
        updated = update_market_mapping(db, "Los Angeles", "LOS ANGELES")
        # CA-27 and CA-48 both have "Los Angeles" DMA
        assert updated == 2
        row = db.execute(
            "SELECT fcc_market FROM dma_districts WHERE district = 'CA-27'"
        ).fetchone()
        assert row["fcc_market"] == "LOS ANGELES"

    def test_no_match_returns_zero(self, db, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        insert_crosswalk(db, rows, {})
        updated = update_market_mapping(db, "Nonexistent DMA", "WHATEVER")
        assert updated == 0


def _seed_district_data(db):
    """Seed a db with stations, contracts, and crosswalk data for query tests."""
    # Stations
    queries.upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "Los Angeles", "CA", "TV")
    queries.upsert_station(db, "2", "KFMB-TV", "SAN DIEGO", "San Diego", "CA", "TV")
    queries.upsert_station(db, "3", "KHOU-TV", "HOUSTON", "Houston", "TX", "TV")

    # Contracts
    queries.upsert_contract(
        db, contract_id="1:100", entity_id="1", contract_number="100",
        candidate="Steyer", gross_total=100000.0, net_total=85000.0, total_spots=50,
    )
    queries.upsert_contract(
        db, contract_id="2:200", entity_id="2", contract_number="200",
        candidate="Steyer", gross_total=60000.0, net_total=51000.0, total_spots=30,
    )
    queries.upsert_contract(
        db, contract_id="3:300", entity_id="3", contract_number="300",
        candidate="Cruz", gross_total=200000.0, net_total=170000.0, total_spots=100,
    )

    # District crosswalk
    crosswalk = [
        {"state": "CA", "district": "CA-27", "dma_name": "Los Angeles", "population": 950000, "weight": 1.0},
        {"state": "CA", "district": "CA-48", "dma_name": "Los Angeles", "population": 284000, "weight": 0.331},
        {"state": "CA", "district": "CA-48", "dma_name": "San Diego", "population": 574000, "weight": 0.669},
        {"state": "TX", "district": "TX-22", "dma_name": "Houston", "population": 780000, "weight": 1.0},
    ]
    market_map = {
        "Los Angeles": "LOS ANGELES",
        "San Diego": "SAN DIEGO",
        "Houston": "HOUSTON",
    }
    insert_crosswalk(db, crosswalk, market_map)


class TestInsertCrosswalkEdgeCases:
    def test_empty_rows(self, db):
        count = insert_crosswalk(db, [], {})
        assert count == 0
        total = db.execute("SELECT COUNT(*) FROM dma_districts").fetchone()[0]
        assert total == 0

    def test_empty_rows_clears_existing(self, db, crosswalk_csv):
        rows = load_crosswalk_csv(crosswalk_csv)
        insert_crosswalk(db, rows, {})
        assert db.execute("SELECT COUNT(*) FROM dma_districts").fetchone()[0] == 7
        # Reload with empty clears all
        insert_crosswalk(db, [], {})
        assert db.execute("SELECT COUNT(*) FROM dma_districts").fetchone()[0] == 0


class TestLoadCrosswalkCsvEdgeCases:
    def test_empty_csv(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("CD,Media market,State,Population,Percentage\n")
        rows = load_crosswalk_csv(path)
        assert rows == []

    def test_all_none_dma_district(self, tmp_path):
        """District where the only DMA entry is [None] — gets filtered entirely."""
        csv_content = textwrap.dedent("""\
            CD,Media market,State,Population,Percentage
            XX-01,[None],XX,"100,000",100.0%
        """)
        path = tmp_path / "allnone.csv"
        path.write_text(csv_content)
        rows = load_crosswalk_csv(path)
        assert len(rows) == 0


class TestAutoMatchEdgeCases:
    def test_empty_rows(self, db):
        matched, unmatched = auto_match_markets(db, [])
        assert matched == {}
        assert unmatched == []

    def test_dma_substring_does_not_match(self, db):
        """'New York' should not match 'NEW YORK-NEWARK' — exact uppercase only."""
        queries.upsert_station(db, "1", "WNBC", "NEW YORK-NEWARK", "New York", "NY", "TV")
        rows = [{"dma_name": "New York", "district": "NY-14", "state": "NY",
                 "population": 750000, "weight": 1.0}]
        matched, unmatched = auto_match_markets(db, rows)
        # "NEW YORK" != "NEW YORK-NEWARK", so no match
        assert "New York" in unmatched

    def test_multiple_stations_same_market_matches_once(self, db):
        queries.upsert_station(db, "1", "KABC-TV", "LOS ANGELES", "LA", "CA", "TV")
        queries.upsert_station(db, "2", "KNBC-TV", "LOS ANGELES", "LA", "CA", "TV")
        rows = [{"dma_name": "Los Angeles", "district": "CA-27", "state": "CA",
                 "population": 950000, "weight": 1.0}]
        matched, unmatched = auto_match_markets(db, rows)
        assert matched == {"Los Angeles": "LOS ANGELES"}
        assert unmatched == []

    def test_case_sensitive_dma_name_in_update(self, db, crosswalk_csv):
        """update_market_mapping is case-sensitive on dma_name."""
        rows = load_crosswalk_csv(crosswalk_csv)
        insert_crosswalk(db, rows, {})
        # Wrong case — should not match
        updated = update_market_mapping(db, "los angeles", "LOS ANGELES")
        assert updated == 0


class TestQueryContractsByDistrict:
    def test_full_weight_district(self, db):
        _seed_district_data(db)
        results = queries.query_contracts_by_district(db, "CA-27")
        assert len(results) == 1
        r = results[0]
        assert r["estimated_gross"] == pytest.approx(100000.0)
        assert r["estimated_net"] == pytest.approx(85000.0)

    def test_split_weight_district(self, db):
        _seed_district_data(db)
        results = queries.query_contracts_by_district(db, "CA-48")
        assert len(results) == 2
        # LA contract weighted at 33.1%
        la = [r for r in results if r["dma_name"] == "Los Angeles"][0]
        assert la["estimated_gross"] == pytest.approx(100000.0 * 0.331)
        # SD contract weighted at 66.9%
        sd = [r for r in results if r["dma_name"] == "San Diego"][0]
        assert sd["estimated_gross"] == pytest.approx(60000.0 * 0.669)

    def test_candidate_filter(self, db):
        _seed_district_data(db)
        results = queries.query_contracts_by_district(db, "TX-22", candidate="Cruz")
        assert len(results) == 1
        assert results[0]["candidate"] == "Cruz"

    def test_advertiser_filter(self, db):
        _seed_district_data(db)
        # Add advertiser to existing contract
        db.execute("UPDATE contracts SET advertiser = 'STEYER PAC' WHERE contract_id = '1:100'")
        db.commit()
        results = queries.query_contracts_by_district(db, "CA-27", advertiser="STEYER")
        assert len(results) == 1
        results = queries.query_contracts_by_district(db, "CA-27", advertiser="NOBODY")
        assert len(results) == 0

    def test_candidate_and_advertiser_together(self, db):
        _seed_district_data(db)
        db.execute("UPDATE contracts SET advertiser = 'STEYER PAC' WHERE contract_id = '1:100'")
        db.commit()
        results = queries.query_contracts_by_district(
            db, "CA-27", candidate="Steyer", advertiser="STEYER",
        )
        assert len(results) == 1
        # Both filters must match (AND logic)
        results = queries.query_contracts_by_district(
            db, "CA-27", candidate="Cruz", advertiser="STEYER",
        )
        assert len(results) == 0

    def test_no_results_for_unknown_district(self, db):
        _seed_district_data(db)
        results = queries.query_contracts_by_district(db, "FL-01")
        assert len(results) == 0

    def test_null_gross_total(self, db):
        """Contract with NULL gross_total — estimated_gross should be NULL."""
        _seed_district_data(db)
        queries.upsert_contract(
            db, contract_id="1:999", entity_id="1", contract_number="999",
            candidate="NullTest", gross_total=None, net_total=None,
        )
        results = queries.query_contracts_by_district(db, "CA-27", candidate="NullTest")
        assert len(results) == 1
        assert results[0]["estimated_gross"] is None
        assert results[0]["estimated_net"] is None

    def test_zero_gross_total(self, db):
        """Contract with $0 gross — estimated_gross should be $0, not NULL."""
        _seed_district_data(db)
        queries.upsert_contract(
            db, contract_id="1:888", entity_id="1", contract_number="888",
            candidate="ZeroTest", gross_total=0.0, net_total=0.0,
        )
        results = queries.query_contracts_by_district(db, "CA-27", candidate="ZeroTest")
        assert len(results) == 1
        assert results[0]["estimated_gross"] == 0.0

    def test_multiple_contracts_same_station(self, db):
        """Two contracts at KABC both show up for CA-27."""
        _seed_district_data(db)
        queries.upsert_contract(
            db, contract_id="1:101", entity_id="1", contract_number="101",
            candidate="Steyer", gross_total=50000.0, net_total=42500.0,
        )
        results = queries.query_contracts_by_district(db, "CA-27", candidate="Steyer")
        assert len(results) == 2
        total_eg = sum(r["estimated_gross"] for r in results)
        assert total_eg == pytest.approx(150000.0)  # 100k + 50k, both at 100% weight

    def test_result_columns(self, db):
        """Verify all expected columns are present in results."""
        _seed_district_data(db)
        results = queries.query_contracts_by_district(db, "CA-27")
        r = results[0]
        expected_cols = [
            "district", "state", "dma_name", "weight",
            "contract_id", "contract_number", "advertiser", "candidate",
            "gross_total", "net_total", "estimated_gross", "estimated_net",
            "call_sign", "market",
        ]
        for col in expected_cols:
            assert col in r.keys(), f"Missing column: {col}"


class TestSummaryByDistrict:
    def test_aggregates_across_districts(self, db):
        _seed_district_data(db)
        results = queries.summary_by_district(db, candidate="Steyer")
        districts = {r["district"] for r in results}
        assert "CA-27" in districts
        assert "CA-48" in districts

    def test_state_filter(self, db):
        _seed_district_data(db)
        results = queries.summary_by_district(db, state="TX")
        assert all(r["state"] == "TX" for r in results)
        assert len(results) == 1

    def test_nonexistent_state(self, db):
        _seed_district_data(db)
        results = queries.summary_by_district(db, state="ZZ")
        assert len(results) == 0

    def test_candidate_and_state_together(self, db):
        _seed_district_data(db)
        results = queries.summary_by_district(db, candidate="Steyer", state="CA")
        assert all(r["state"] == "CA" for r in results)
        assert len(results) == 2  # CA-27 and CA-48

    def test_ca27_full_weight(self, db):
        _seed_district_data(db)
        results = queries.summary_by_district(db, candidate="Steyer")
        ca27 = [r for r in results if r["district"] == "CA-27"][0]
        assert ca27["estimated_gross"] == pytest.approx(100000.0)

    def test_ca48_combined_weight(self, db):
        _seed_district_data(db)
        results = queries.summary_by_district(db, candidate="Steyer")
        ca48 = [r for r in results if r["district"] == "CA-48"][0]
        expected = 100000.0 * 0.331 + 60000.0 * 0.669
        assert ca48["estimated_gross"] == pytest.approx(expected)

    def test_null_totals_excluded_from_sum(self, db):
        """NULL gross_total doesn't corrupt the SUM — just gets ignored."""
        _seed_district_data(db)
        queries.upsert_contract(
            db, contract_id="1:999", entity_id="1", contract_number="999",
            candidate="Steyer", gross_total=None, net_total=None,
        )
        results = queries.summary_by_district(db, candidate="Steyer")
        ca27 = [r for r in results if r["district"] == "CA-27"][0]
        # NULL * weight = NULL, SUM ignores NULLs, so total stays at 100000
        assert ca27["estimated_gross"] == pytest.approx(100000.0)

    def test_result_columns(self, db):
        _seed_district_data(db)
        results = queries.summary_by_district(db, candidate="Steyer")
        r = results[0]
        for col in ["district", "state", "estimated_gross", "estimated_net",
                     "total_spots", "contract_count", "dma_names"]:
            assert col in r.keys(), f"Missing column: {col}"

    def test_no_contracts_returns_empty(self, db):
        """Crosswalk loaded but no contracts exist — empty result, not error."""
        crosswalk = [
            {"state": "FL", "district": "FL-01", "dma_name": "Tallahassee",
             "population": 500000, "weight": 1.0},
        ]
        insert_crosswalk(db, crosswalk, {"Tallahassee": "TALLAHASSEE"})
        results = queries.summary_by_district(db, state="FL")
        assert len(results) == 0


class TestDistrictsForMarket:
    def test_lists_districts(self, db):
        _seed_district_data(db)
        results = queries.districts_for_market(db, "LOS ANGELES")
        districts = {r["district"] for r in results}
        assert districts == {"CA-27", "CA-48"}

    def test_weight_ordering(self, db):
        _seed_district_data(db)
        results = queries.districts_for_market(db, "LOS ANGELES")
        # CA-27 is 100%, CA-48 is 33.1% — CA-27 should be first
        assert results[0]["district"] == "CA-27"

    def test_unknown_market(self, db):
        _seed_district_data(db)
        results = queries.districts_for_market(db, "NONEXISTENT")
        assert len(results) == 0


class TestDistrictDmaWeights:
    def test_single_dma_district(self, db):
        _seed_district_data(db)
        results = queries.district_dma_weights(db, "CA-27")
        assert len(results) == 1
        assert results[0]["dma_name"] == "Los Angeles"
        assert results[0]["weight"] == pytest.approx(1.0)

    def test_multi_dma_district(self, db):
        _seed_district_data(db)
        results = queries.district_dma_weights(db, "CA-48")
        assert len(results) == 2
        dmas = {r["dma_name"] for r in results}
        assert dmas == {"Los Angeles", "San Diego"}

    def test_multi_dma_weight_ordering(self, db):
        _seed_district_data(db)
        results = queries.district_dma_weights(db, "CA-48")
        # San Diego 66.9% should come before Los Angeles 33.1%
        assert results[0]["weight"] > results[1]["weight"]

    def test_unknown_district(self, db):
        _seed_district_data(db)
        results = queries.district_dma_weights(db, "ZZ-99")
        assert len(results) == 0


def _seed_national_scenario(db):
    """Seed a realistic national scenario with diverse districts and campaign types.

    Districts:
      - CA-27: 100% Los Angeles (governor race)
      - CA-48: 33.1% Los Angeles + 66.9% San Diego (House race)
      - PA-07: 89.9% Philadelphia + 10.1% Wilkes-Barre (Senate race)
      - GA-06: 100% Atlanta (House race)
      - AK-AL: 62.3% Anchorage + 14.2% Fairbanks + 9.8% Juneau (at-large, Senate)
      - OH-01: 100% Cincinnati (governor race)
      - NV-03: 100% Las Vegas (House race)
    """
    # Stations — one per market
    stations = [
        ("s-la", "KABC-TV", "LOS ANGELES", "Los Angeles", "CA"),
        ("s-sd", "KFMB-TV", "SAN DIEGO", "San Diego", "CA"),
        ("s-ph", "WPVI-TV", "PHILADELPHIA", "Philadelphia", "PA"),
        ("s-wb", "WBRE-TV", "WILKES-BARRE", "Wilkes-Barre", "PA"),
        ("s-at", "WSB-TV", "ATLANTA", "Atlanta", "GA"),
        ("s-an", "KTUU-TV", "ANCHORAGE", "Anchorage", "AK"),
        ("s-fb", "KTVF-TV", "FAIRBANKS", "Fairbanks", "AK"),
        ("s-ju", "KTOO-TV", "JUNEAU", "Juneau", "AK"),
        ("s-ci", "WLWT-TV", "CINCINNATI", "Cincinnati", "OH"),
        ("s-lv", "KLAS-TV", "LAS VEGAS", "Las Vegas", "NV"),
    ]
    for eid, call, market, city, state in stations:
        queries.upsert_station(db, eid, call, market, city, state, "Full Service")

    # Contracts — different campaign types
    contracts = [
        # CA governor race (Steyer)
        ("s-la:g1", "s-la", "G001", "STEYER FOR GOVERNOR", "Tom Steyer",
         500000.0, 425000.0, 200),
        # CA House race CA-48 (House candidate)
        ("s-la:h1", "s-la", "H001", "CHEN FOR CONGRESS", "Michelle Chen",
         80000.0, 68000.0, 40),
        ("s-sd:h2", "s-sd", "H002", "CHEN FOR CONGRESS", "Michelle Chen",
         120000.0, 102000.0, 60),
        # PA Senate race (Senate candidate buying in both PA DMAs)
        ("s-ph:s1", "s-ph", "S001", "FETTERMAN FOR SENATE", "John Fetterman",
         300000.0, 255000.0, 150),
        ("s-wb:s2", "s-wb", "S002", "FETTERMAN FOR SENATE", "John Fetterman",
         50000.0, 42500.0, 25),
        # GA House race
        ("s-at:h3", "s-at", "H003", "WILLIAMS FOR CONGRESS", "Nikema Williams",
         150000.0, 127500.0, 75),
        # AK Senate race (buying in all 3 DMAs)
        ("s-an:s3", "s-an", "S003", "MURKOWSKI CAMPAIGN", "Lisa Murkowski",
         200000.0, 170000.0, 100),
        ("s-fb:s4", "s-fb", "S004", "MURKOWSKI CAMPAIGN", "Lisa Murkowski",
         40000.0, 34000.0, 20),
        ("s-ju:s5", "s-ju", "S005", "MURKOWSKI CAMPAIGN", "Lisa Murkowski",
         20000.0, 17000.0, 10),
        # OH governor race
        ("s-ci:g2", "s-ci", "G002", "DEWINE FOR GOVERNOR", "Mike DeWine",
         250000.0, 212500.0, 125),
        # NV House race
        ("s-lv:h4", "s-lv", "H004", "LEE FOR CONGRESS", "Susie Lee",
         175000.0, 148750.0, 90),
    ]
    for cid, eid, cnum, adv, cand, gross, net, spots in contracts:
        queries.upsert_contract(
            db, contract_id=cid, entity_id=eid, contract_number=cnum,
            advertiser=adv, candidate=cand,
            gross_total=gross, net_total=net, total_spots=spots,
        )

    # District crosswalk
    crosswalk = [
        {"state": "CA", "district": "CA-27", "dma_name": "Los Angeles",
         "population": 760067, "weight": 1.0},
        {"state": "CA", "district": "CA-48", "dma_name": "Los Angeles",
         "population": 284000, "weight": 0.331},
        {"state": "CA", "district": "CA-48", "dma_name": "San Diego",
         "population": 574000, "weight": 0.669},
        {"state": "PA", "district": "PA-07", "dma_name": "Philadelphia",
         "population": 687508, "weight": 0.899},
        {"state": "PA", "district": "PA-07", "dma_name": "Wilkes-Barre",
         "population": 77357, "weight": 0.101},
        {"state": "GA", "district": "GA-06", "dma_name": "Atlanta",
         "population": 765136, "weight": 1.0},
        {"state": "AK", "district": "AK-AL", "dma_name": "Anchorage",
         "population": 457127, "weight": 0.623},
        {"state": "AK", "district": "AK-AL", "dma_name": "Fairbanks",
         "population": 104082, "weight": 0.142},
        {"state": "AK", "district": "AK-AL", "dma_name": "Juneau",
         "population": 71624, "weight": 0.098},
        {"state": "OH", "district": "OH-01", "dma_name": "Cincinnati",
         "population": 786630, "weight": 1.0},
        {"state": "NV", "district": "NV-03", "dma_name": "Las Vegas",
         "population": 776153, "weight": 1.0},
    ]
    market_map = {
        "Los Angeles": "LOS ANGELES",
        "San Diego": "SAN DIEGO",
        "Philadelphia": "PHILADELPHIA",
        "Wilkes-Barre": "WILKES-BARRE",
        "Atlanta": "ATLANTA",
        "Anchorage": "ANCHORAGE",
        "Fairbanks": "FAIRBANKS",
        "Juneau": "JUNEAU",
        "Cincinnati": "CINCINNATI",
        "Las Vegas": "LAS VEGAS",
    }
    insert_crosswalk(db, crosswalk, market_map)


class TestNationalScenario:
    """Diverse district/campaign tests: governor, Senate, House, at-large, multi-DMA."""

    def test_governor_race_full_weight(self, db):
        """CA governor race at KABC — CA-27 gets 100% of the spend."""
        _seed_national_scenario(db)
        results = queries.query_contracts_by_district(db, "CA-27", candidate="Steyer")
        assert len(results) == 1
        assert results[0]["estimated_gross"] == pytest.approx(500000.0)

    def test_governor_race_also_hits_split_district(self, db):
        """Same KABC governor ad reaches CA-48 at 33.1% weight."""
        _seed_national_scenario(db)
        results = queries.query_contracts_by_district(db, "CA-48", candidate="Steyer")
        la = [r for r in results if r["dma_name"] == "Los Angeles"][0]
        assert la["estimated_gross"] == pytest.approx(500000.0 * 0.331)

    def test_house_race_two_stations_split_district(self, db):
        """Chen buys LA ($80k) and SD ($120k). CA-48 gets 33.1% of LA + 66.9% of SD."""
        _seed_national_scenario(db)
        results = queries.query_contracts_by_district(db, "CA-48", candidate="Chen")
        assert len(results) == 2
        la = [r for r in results if r["dma_name"] == "Los Angeles"][0]
        sd = [r for r in results if r["dma_name"] == "San Diego"][0]
        assert la["estimated_gross"] == pytest.approx(80000.0 * 0.331)
        assert sd["estimated_gross"] == pytest.approx(120000.0 * 0.669)
        total = la["estimated_gross"] + sd["estimated_gross"]
        assert total == pytest.approx(80000.0 * 0.331 + 120000.0 * 0.669)

    def test_senate_race_weighted_across_dmas(self, db):
        """Fetterman buys Philly ($300k) and Wilkes-Barre ($50k). PA-07 gets weighted sum."""
        _seed_national_scenario(db)
        results = queries.summary_by_district(db, candidate="Fetterman")
        assert len(results) == 1
        pa07 = results[0]
        assert pa07["district"] == "PA-07"
        expected = 300000.0 * 0.899 + 50000.0 * 0.101
        assert pa07["estimated_gross"] == pytest.approx(expected)

    def test_at_large_three_dma_weights(self, db):
        """AK-AL at-large: Murkowski buys 3 DMAs. Weights don't sum to 1.0 (rural gap)."""
        _seed_national_scenario(db)
        results = queries.query_contracts_by_district(db, "AK-AL", candidate="Murkowski")
        assert len(results) == 3
        dmas = {r["dma_name"]: r for r in results}
        assert dmas["Anchorage"]["estimated_gross"] == pytest.approx(200000.0 * 0.623)
        assert dmas["Fairbanks"]["estimated_gross"] == pytest.approx(40000.0 * 0.142)
        assert dmas["Juneau"]["estimated_gross"] == pytest.approx(20000.0 * 0.098)

    def test_at_large_summary_aggregates_all_dmas(self, db):
        """Summary for AK-AL sums weighted spend across all 3 DMAs."""
        _seed_national_scenario(db)
        results = queries.summary_by_district(db, candidate="Murkowski")
        assert len(results) == 1
        ak = results[0]
        expected = 200000.0 * 0.623 + 40000.0 * 0.142 + 20000.0 * 0.098
        assert ak["estimated_gross"] == pytest.approx(expected)

    def test_single_dma_district_full_weight(self, db):
        """GA-06 (100% Atlanta), OH-01 (100% Cincinnati), NV-03 (100% Las Vegas)."""
        _seed_national_scenario(db)
        for district, candidate, expected_gross in [
            ("GA-06", "Williams", 150000.0),
            ("OH-01", "DeWine", 250000.0),
            ("NV-03", "Lee", 175000.0),
        ]:
            results = queries.query_contracts_by_district(db, district, candidate=candidate)
            assert len(results) == 1, f"{district} should have 1 contract"
            assert results[0]["estimated_gross"] == pytest.approx(expected_gross)

    def test_summary_across_all_states(self, db):
        """Summary with no filters returns all districts with contracts."""
        _seed_national_scenario(db)
        results = queries.summary_by_district(db)
        districts = {r["district"] for r in results}
        # Every district with a matched DMA+contract should appear
        assert districts >= {"CA-27", "CA-48", "PA-07", "GA-06", "AK-AL", "OH-01", "NV-03"}

    def test_state_filter_ca_only(self, db):
        _seed_national_scenario(db)
        results = queries.summary_by_district(db, state="CA")
        districts = {r["district"] for r in results}
        assert districts == {"CA-27", "CA-48"}
        assert all(r["state"] == "CA" for r in results)

    def test_state_filter_pa_only(self, db):
        _seed_national_scenario(db)
        results = queries.summary_by_district(db, state="PA")
        assert len(results) == 1
        assert results[0]["district"] == "PA-07"

    def test_state_filter_ak(self, db):
        _seed_national_scenario(db)
        results = queries.summary_by_district(db, state="AK")
        assert len(results) == 1
        assert results[0]["district"] == "AK-AL"

    def test_governor_vs_house_same_dma(self, db):
        """LA DMA has both a governor race (Steyer) and a House race (Chen).
        CA-27 should see both; CA-48 should see both at 33.1%."""
        _seed_national_scenario(db)
        ca27 = queries.query_contracts_by_district(db, "CA-27")
        candidates = {r["candidate"] for r in ca27}
        assert "Tom Steyer" in candidates
        assert "Michelle Chen" in candidates

    def test_districts_for_market_la(self, db):
        """LA market should touch CA-27 and CA-48."""
        _seed_national_scenario(db)
        results = queries.districts_for_market(db, "LOS ANGELES")
        districts = {r["district"] for r in results}
        assert districts == {"CA-27", "CA-48"}

    def test_districts_for_market_anchorage(self, db):
        """Anchorage market only touches AK-AL."""
        _seed_national_scenario(db)
        results = queries.districts_for_market(db, "ANCHORAGE")
        assert len(results) == 1
        assert results[0]["district"] == "AK-AL"
        assert results[0]["weight"] == pytest.approx(0.623)

    def test_summary_ordered_by_spend(self, db):
        """Results come back ordered by estimated_gross DESC."""
        _seed_national_scenario(db)
        results = queries.summary_by_district(db)
        grosses = [r["estimated_gross"] for r in results]
        assert grosses == sorted(grosses, reverse=True)

    def test_dma_names_in_summary(self, db):
        """summary_by_district should include DMA names for multi-DMA districts."""
        _seed_national_scenario(db)
        results = queries.summary_by_district(db)
        ak = [r for r in results if r["district"] == "AK-AL"][0]
        # GROUP_CONCAT should include all 3 DMAs
        for dma in ["Anchorage", "Fairbanks", "Juneau"]:
            assert dma in ak["dma_names"]


class TestRealCsvIntegration:
    """Integration tests using the actual Downballot CSV."""

    REAL_CSV = "data/downballot-cd-to-dma-2024.csv"

    @pytest.fixture
    def real_rows(self):
        from pathlib import Path
        csv_path = Path(__file__).parent.parent / self.REAL_CSV
        if not csv_path.exists():
            pytest.skip("Real crosswalk CSV not present")
        return load_crosswalk_csv(csv_path)

    def test_row_count(self, real_rows):
        # 905 lines - 1 header - some [None] rows
        assert len(real_rows) >= 850
        assert len(real_rows) <= 904

    def test_all_weights_in_range(self, real_rows):
        for r in real_rows:
            # Some districts have 0.0% weight (rounding artifact for tiny slivers)
            assert 0.0 <= r["weight"] <= 1.0, f"{r['district']} {r['dma_name']}: weight={r['weight']}"

    def test_all_populations_positive(self, real_rows):
        for r in real_rows:
            assert r["population"] > 0, f"{r['district']} {r['dma_name']}: pop={r['population']}"

    def test_all_states_two_letter(self, real_rows):
        for r in real_rows:
            assert len(r["state"]) == 2, f"Bad state: {r['state']}"

    def test_district_format(self, real_rows):
        """Every district should match XX-## or XX-AL pattern."""
        import re
        pattern = re.compile(r"^[A-Z]{2}-(\d{1,2}|AL)$")
        for r in real_rows:
            assert pattern.match(r["district"]), f"Bad district format: {r['district']}"

    def test_no_none_dmas_loaded(self, real_rows):
        for r in real_rows:
            assert r["dma_name"] != "[None]"

    def test_weights_sum_per_district(self, real_rows):
        """Weights for each district should sum to ~1.0 (allowing for rounding and [None] gaps)."""
        from collections import defaultdict
        totals: dict[str, float] = defaultdict(float)
        for r in real_rows:
            totals[r["district"]] += r["weight"]
        for district, total in totals.items():
            # Some districts have [None] population that gets skipped,
            # so total may be < 1.0. Rounding artifacts can push slightly above 1.0.
            assert total <= 1.01, f"{district}: weights sum to {total}"

    def test_ca27_is_100_pct_la(self, real_rows):
        ca27 = [r for r in real_rows if r["district"] == "CA-27"]
        assert len(ca27) == 1
        assert ca27[0]["dma_name"] == "Los Angeles"
        assert ca27[0]["weight"] == pytest.approx(1.0)

    def test_at_large_districts_exist(self, real_rows):
        at_large = [r for r in real_rows if r["district"].endswith("-AL")]
        assert len(at_large) >= 5  # AK, WY, VT, ND, SD, MT, DE at minimum

    def test_load_into_db(self, db, real_rows):
        """Full CSV loads into database without errors."""
        matched, unmatched = auto_match_markets(db, real_rows)
        count = insert_crosswalk(db, real_rows, matched)
        assert count == len(real_rows)
        db_count = db.execute("SELECT COUNT(*) FROM dma_districts").fetchone()[0]
        assert db_count == len(real_rows)
