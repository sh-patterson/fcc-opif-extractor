import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from fcc_ad_tracker.client import OpifClient

logger = logging.getLogger(__name__)

US_STATE_CODES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
]


@dataclass(frozen=True)
class Station:
    entity_id: str
    call_sign: str
    market: str
    city: str
    state: str
    service_type: str

    @classmethod
    def from_facility(cls, facility: dict) -> "Station":
        community = facility.get("community") or {}
        return cls(
            entity_id=str(facility["id"]),
            call_sign=facility["callSign"],
            market=facility.get("nielsenDma", ""),
            city=community.get("city", facility.get("communityCity", "")),
            state=community.get("state", facility.get("communityState", "")),
            service_type=facility.get("service", facility.get("serviceType", "")),
        )

    @property
    def is_full_power(self) -> bool:
        return _is_full_power_facility({"service": self.service_type})


def _is_full_power_facility(facility: dict) -> bool:
    service = str(facility.get("service", facility.get("serviceType", ""))).lower()
    if "low power" in service:
        return False
    return (
        ("full" in service and ("service" in service or "power" in service))
        or ("class" in service and "a" in service)
        or str(facility.get("facilityType", "")).upper() in {"CDT", "EDT"}
    )


def _extract_facilities(data: dict) -> list[dict]:
    """Extract facility dicts from facility search response.

    Current responses expose TV matches in globalSearchResults.tvFacilityList.
    Legacy responses used searchList categories with nested facilityList values.
    """
    results = data.get("results", {})
    global_results = results.get("globalSearchResults", {})
    current_facilities = global_results.get("tvFacilityList")
    if isinstance(current_facilities, list):
        return current_facilities

    facilities = []
    search_list = results.get("searchList", [])
    for entry in search_list:
        facilities.extend(entry.get("facilityList", []))
    return facilities


def discover_stations(
    client: OpifClient,
    state: str = "CA",
    target_dmas: list[str] | None = None,
    full_power_only: bool = True,
) -> list[Station]:
    data = client.search_facilities(state)
    facilities = _extract_facilities(data)
    requested_state = state.strip().casefold()
    stations = []
    for facility in facilities:
        station = Station.from_facility(facility)
        if station.state.casefold() != requested_state:
            continue
        if full_power_only and not _is_full_power_facility(facility):
            continue
        stations.append(station)
    if target_dmas:
        normalized_dmas = {dma.casefold() for dma in target_dmas}
        stations = [s for s in stations if s.market.casefold() in normalized_dmas]

    logger.info(
        "Discovered %d stations in %s (filtered from %d facilities)",
        len(stations),
        state,
        len(facilities),
    )
    return stations


def discover_stations_by_dmas(
    client: OpifClient,
    *,
    target_dmas: list[str],
    states: list[str] | None = None,
    full_power_only: bool = True,
) -> list[Station]:
    """Discover stations in target DMAs across many states to handle cross-state markets."""
    states_to_search = states or US_STATE_CODES
    by_entity: dict[str, Station] = {}
    for state in states_to_search:
        for station in discover_stations(
            client,
            state=state,
            target_dmas=target_dmas,
            full_power_only=full_power_only,
        ):
            by_entity[station.entity_id] = station
    stations = sorted(by_entity.values(), key=lambda s: (s.market, s.call_sign))
    logger.info(
        "Discovered %d stations across %d states for DMAs=%s",
        len(stations),
        len(states_to_search),
        ",".join(target_dmas),
    )
    return stations


def save_stations(stations: list[Station], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(s) for s in stations]
    path.write_text(json.dumps(data, indent=2))


def load_stations(path: Path) -> list[Station]:
    data = json.loads(path.read_text())
    return [Station(**d) for d in data]
