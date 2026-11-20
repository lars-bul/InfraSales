import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from infrasales.projects.models import MetricKind
from infrasales.sources.zensus import read_pages


def page(path: Path, rows: Sequence[Mapping[str, object]]) -> Path:
    path.mkdir()
    (path / "page-0.json").write_text(
        json.dumps({"features": [{"attributes": row} for row in rows]}), encoding="utf-8"
    )
    return path


def test_a_municipalitys_buildings_are_read_as_shares(tmp_path: Path) -> None:
    carriers = {
        f"ENERGIETRAEGER__{i}": n
        for i, n in enumerate([500, 200, 50, 10, 30, 20, 0, 180, 10], start=1)
    }
    row = {
        "AGS": "08221000",
        "GEBAEUDEART_SYS_1": 1000,
        **carriers,
        "ZAHLWOHNGN_HHG__4": 100,
        "ZAHLWOHNGN_HHG__5": 50,
        "EIGENTUM__3": 10,
        "EIGENTUM__4": 20,
        "EIGENTUM__5": None,  # kept secret: a handful
    }

    figures = {f.metric: f.value for f in read_pages(page(tmp_path / "z", [row]))}

    assert figures[MetricKind.BUILDINGS] == 1000
    assert figures[MetricKind.DISTRICT_HEATING_SHARE] == pytest.approx(0.18)
    assert figures[MetricKind.GAS_HEATING_SHARE] == pytest.approx(0.5)
    assert figures[MetricKind.MULTI_FAMILY_SHARE] == pytest.approx(0.15)
    assert figures[MetricKind.HOUSING_COMPANY_SHARE] == pytest.approx(0.03)
    assert MetricKind.OLD_BUILDING_SHARE not in figures  # not counted there: no figure


def test_without_a_total_the_energy_carriers_count_the_buildings(tmp_path: Path) -> None:
    row = {
        "AGS": "01051002",
        "GEBAEUDEART_SYS_1": None,
        "ENERGIETRAEGER__1": 30,
        "ENERGIETRAEGER__2": 70,
    }

    figures = {f.metric: f.value for f in read_pages(page(tmp_path / "z", [row, {"AGS": "x"}]))}

    assert figures[MetricKind.BUILDINGS] == 100
    assert figures[MetricKind.DISTRICT_HEATING_SHARE] == 0.0  # none told: none there
