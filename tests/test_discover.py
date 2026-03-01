import json
from pathlib import Path

import responses

from fcc_ca_ads.config import OpifConfig, CA_TARGET_DMAS
from fcc_ca_ads.client import OpifClient
from fcc_ca_ads.discover import Station, discover_stations, save_stations, load_stations

FIXTURES = Path(__file__).parent / "fixtures"


def test_station_from_facility():
    facility = {
        "id": 25452,
        "callSign": "KABC-TV",
        "community": {"city": "LOS ANGELES", "state": "CA"},
        "nielsenDma": "LOS ANGELES",
        "service": "Full Service",
    }
    station = Station.from_facility(facility)
    assert station.entity_id == "25452"
    assert station.call_sign == "KABC-TV"
    assert station.market == "LOS ANGELES"
    assert station.is_full_power is True


def test_station_low_power_excluded():
    facility = {
        "id": 99999,
        "callSign": "K99ZZ-LP",
        "community": {"city": "BAKERSFIELD", "state": "CA"},
        "nielsenDma": "BAKERSFIELD",
        "service": "Low Power",
    }
    station = Station.from_facility(facility)
    assert station.is_full_power is False


@responses.activate
def test_discover_stations_filters_by_dma():
    cfg = OpifConfig(rate_limit_delay=0.0)
    client = OpifClient(cfg)
    fixture = json.loads((FIXTURES / "facility_search_ca.json").read_text())
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/service/tv/facility/search/CA.json",
        json=fixture,
        status=200,
    )
    stations = discover_stations(client, state="CA", target_dmas=CA_TARGET_DMAS)
    # Should include LA, SF, Sacramento stations but not Bakersfield
    call_signs = [s.call_sign for s in stations]
    assert "KABC-TV" in call_signs
    assert "KPIX-TV" in call_signs
    assert "KXTV" in call_signs
    assert "KBAK-TV" not in call_signs
    # Low power should be excluded
    assert "K99ZZ-LP" not in call_signs


@responses.activate
def test_discover_stations_full_power_only():
    cfg = OpifConfig(rate_limit_delay=0.0)
    client = OpifClient(cfg)
    fixture = json.loads((FIXTURES / "facility_search_ca.json").read_text())
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/service/tv/facility/search/CA.json",
        json=fixture,
        status=200,
    )
    stations = discover_stations(
        client, state="CA", target_dmas=["LOS ANGELES"], full_power_only=True
    )
    call_signs = [s.call_sign for s in stations]
    assert "K99ZZ-LP" not in call_signs


def test_save_and_load_stations(tmp_path):
    stations = [
        Station(
            entity_id="1",
            call_sign="KABC-TV",
            market="LOS ANGELES",
            city="LOS ANGELES",
            state="CA",
            service_type="Full Service",
        ),
    ]
    path = tmp_path / "stations.json"
    save_stations(stations, path)
    loaded = load_stations(path)
    assert len(loaded) == 1
    assert loaded[0].entity_id == "1"
    assert loaded[0].call_sign == "KABC-TV"
