"""What each sector's projects state in figures: one versioned schema per sector (ADR 06 §2).

A new sector is a schema here and a value of `Sector`; no table changes. A schema that changes
what a stored value means gets a new version, and the facts are computed again.
"""

from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from infrasales.projects.models import Sector


class HeatSource(StrEnum):
    GEOTHERMAL = "geothermal"
    HEAT_PUMP = "heat_pump"  # a large heat pump: river, lake, sewage, air
    WASTE_HEAT = "waste_heat"  # industry, data centres
    BIOMASS = "biomass"
    SOLAR_THERMAL = "solar_thermal"
    WASTE_INCINERATION = "waste_incineration"
    CHP = "chp"  # combined heat and power, by any fuel
    OTHER = "other"


class Facts(BaseModel):
    """What every sector's facts share: unknown fields are refused, every field may be unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class HeatNetworkFacts(Facts):
    trench_length_km: float | None = Field(default=None, gt=0, lt=10_000)
    capacity_mw: float | None = Field(default=None, gt=0, lt=100_000)  # thermal
    connections: int | None = Field(default=None, ge=0)  # buildings connected or planned
    investment_eur: int | None = Field(default=None, ge=0)
    heat_sources: list[HeatSource] = Field(default_factory=list[HeatSource])
    target_year: int | None = Field(default=None, ge=2000, le=2100)  # when it is to supply
    area: str | None = Field(default=None, max_length=300)  # the district or suitable area


SCHEMAS: Mapping[Sector, tuple[type[Facts], int]] = {
    Sector.HEAT_NETWORK: (HeatNetworkFacts, 1),
}


def schema(sector: Sector) -> type[Facts]:
    return SCHEMAS[sector][0]


def version(sector: Sector) -> int:
    return SCHEMAS[sector][1]


def fields(sector: Sector) -> frozenset[str]:
    """The names a claim may set in `sector`'s facts."""
    return frozenset(schema(sector).model_fields)
