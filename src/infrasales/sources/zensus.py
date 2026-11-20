"""The 2022 census by municipality: how buildings are heated, how large and whose they are.

Esri Deutschland serves the census results of the Statistische Ämter des Bundes und der Länder by
municipality as a feature service ("Zensus 2022 - Gebäude und Wohnungen auf Gemeindeebene",
Datenlizenz Deutschland - Namensnennung 2.0: "© Statistische Ämter des Bundes und der Länder,
2024"). Its query pages (`…/Wohnen_Zensus2022/FeatureServer/1/query?…&f=json`) are read here
into shares of a municipality's buildings with dwellings.

The figures describe the building stock on the census day, 15 May 2022; they are used from that
day on (`available_on`). They were published in June 2024, but they hold nothing of what came
after the census day, so a forecast learning from them learns no outcome it predicts.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from infrasales.projects.models import MetricKind

CENSUS_DAY = date(2022, 5, 15)
SOURCE = "zensus-2022"
QUERY_URL = (
    "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/Wohnen_Zensus2022/"
    "FeatureServer/1/query?where=1%3D1&outFields=*&returnGeometry=false&f=json"
)
TOTAL = "GEBAEUDEART_SYS_1"  # buildings with dwellings
SHARES: dict[MetricKind, tuple[str, ...]] = {
    MetricKind.DISTRICT_HEATING_SHARE: ("ENERGIETRAEGER__8",),
    MetricKind.GAS_HEATING_SHARE: ("ENERGIETRAEGER__1",),
    MetricKind.OIL_HEATING_SHARE: ("ENERGIETRAEGER__2",),
    MetricKind.HEAT_PUMP_SHARE: ("ENERGIETRAEGER__5",),
    MetricKind.MULTI_FAMILY_SHARE: ("ZAHLWOHNGN_HHG__4", "ZAHLWOHNGN_HHG__5"),
    MetricKind.HOUSING_COMPANY_SHARE: ("EIGENTUM__3", "EIGENTUM__4", "EIGENTUM__5"),
    MetricKind.OLD_BUILDING_SHARE: tuple(f"BAUJAHR_10JA__0{i}" for i in range(1, 6)),
}


@dataclass(frozen=True, slots=True)
class CensusMetric:
    ags: str
    metric: MetricKind
    value: float


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def read_pages(folder: Path) -> Iterator[CensusMetric]:
    """Every municipality's shares, from the stored query pages (`page-*.json`)."""
    for path in sorted(folder.glob("page-*.json")):
        for feature in json.loads(path.read_text(encoding="utf-8")).get("features", []):
            yield from metrics_of(feature.get("attributes", {}))


def metrics_of(row: dict[str, object]) -> Iterator[CensusMetric]:
    """A municipality's shares of its buildings with dwellings.

    The service leaves out many totals, and counts kept secret (a handful of buildings) are
    empty. The buildings are counted by their energy carriers, which every heated or unheated
    building has one of; an empty count among others is taken as none.
    """
    ags = str(row.get("AGS") or "")
    carriers = [_number(row.get(f"ENERGIETRAEGER__{i}")) for i in range(1, 10)]
    total = _number(row.get(TOTAL)) or sum(c or 0.0 for c in carriers)
    if len(ags) != 8 or not ags.isdigit() or not total:  # noqa: PLR2004  # an AGS has 8 digits
        return
    yield CensusMetric(ags, MetricKind.BUILDINGS, total)
    for metric, fields in SHARES.items():
        counts = [_number(row.get(name)) for name in fields]
        carrier = all(name.startswith("ENERGIETRAEGER") for name in fields)
        if all(count is None for count in counts) and not (carrier and any(carriers)):
            continue  # not counted there at all: no figure, not zero
        yield CensusMetric(ags, metric, min(1.0, round(sum(c or 0.0 for c in counts) / total, 4)))
