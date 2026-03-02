import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from fcc_ca_ads.client import OpifClient

logger = logging.getLogger(__name__)


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
        community = facility.get("community", {})
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
        svc = self.service_type.lower()
        return "full" in svc and ("service" in svc or "power" in svc)


def _extract_facilities(data: dict) -> list[dict]:
    """Extract facility dicts from facility search response.

    The API returns searchList with searchType categories, each containing
    a facilityList. We flatten all facilityList entries.
    """
    facilities = []
    search_list = data.get("results", {}).get("searchList", [])
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
    stations = [Station.from_facility(f) for f in facilities]

    if full_power_only:
        stations = [s for s in stations if s.is_full_power]
    if target_dmas:
        stations = [s for s in stations if s.market in target_dmas]

    logger.info(
        "Discovered %d stations in %s (filtered from %d facilities)",
        len(stations),
        state,
        len(facilities),
    )
    return stations


def save_stations(stations: list[Station], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(s) for s in stations]
    path.write_text(json.dumps(data, indent=2))


def load_stations(path: Path) -> list[Station]:
    data = json.loads(path.read_text())
    return [Station(**d) for d in data]
