import pytest
from pydantic import ValidationError

from infrasales.projects import sectors
from infrasales.projects.models import Sector
from infrasales.projects.sectors import HeatNetworkFacts, HeatSource


def test_every_sector_has_a_schema_and_a_version() -> None:
    assert set(sectors.SCHEMAS) == set(Sector)
    assert all(sectors.version(sector) >= 1 for sector in Sector)


def test_a_heat_network_states_its_figures_and_heat_sources() -> None:
    facts = HeatNetworkFacts.model_validate(
        {"trench_length_km": 4.2, "connections": 900, "heat_sources": ["heat_pump"]}
    )

    assert facts.heat_sources == [HeatSource.HEAT_PUMP]
    assert sectors.schema(Sector.HEAT_NETWORK) is HeatNetworkFacts
    assert {"trench_length_km", "capacity_mw", "target_year"} <= sectors.fields(Sector.HEAT_NETWORK)


@pytest.mark.parametrize(
    "facts",
    [
        {"trench_length_km": 0},
        {"connections": -1},
        {"target_year": 1990},
        {"heat_sources": ["coal-free"]},
        {"pipe_material": "steel"},  # a field heat networks do not have
    ],
)
def test_figures_that_cannot_be_are_refused(facts: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        HeatNetworkFacts.model_validate(facts)
