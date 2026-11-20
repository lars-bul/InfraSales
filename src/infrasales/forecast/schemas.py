"""What the forecast API answers: the ranking, a municipality's file, the models."""

import uuid
from collections.abc import Mapping
from datetime import date, datetime

from pydantic import BaseModel, Field

from infrasales.core.models import JSONValue
from infrasales.forecast.models import ForecastModel, ModelKind
from infrasales.projects.models import (
    SignalKind,
    TenderKind,
    TenderOrigin,
    TenderStatus,
)


class RankingQuery(BaseModel):
    region: str = Field(
        default="",
        pattern=r"^\d{0,8}$",
        description="An AGS prefix: 08 Baden-Württemberg, 082 Regierungsbezirk Karlsruhe, …",
    )
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class ReasonRead(BaseModel):
    feature: str  # a name of `infrasales.forecast.features.FEATURES`
    value: float
    effect: float  # how much it lifts the score above the day's typical municipality


class ModelSummary(BaseModel):
    version: str
    kind: ModelKind
    horizon_months: int
    calibrated: bool  # the score is a probability; otherwise it only orders

    @classmethod
    def of(cls, model: ForecastModel) -> ModelSummary:
        return cls(
            version=model.version,
            kind=model.kind,
            horizon_months=model.horizon_months,
            calibrated=model.kind is ModelKind.LOGISTIC,
        )


class RankedMunicipality(BaseModel):
    rank: int
    ags: str
    name: str
    population: int | None
    score: float
    reasons: list[ReasonRead]


class Ranking(BaseModel):
    model: ModelSummary | None  # None: nothing scored yet
    as_of: date | None
    total: int
    items: list[RankedMunicipality]


class ScorePoint(BaseModel):
    as_of: date
    score: float


class SignalRead(BaseModel):
    kind: SignalKind
    occurred_on: date | None
    available_on: date
    note: str
    url: str | None


class TenderRead(BaseModel):
    origin: TenderOrigin
    kind: TenderKind
    status: TenderStatus
    title: str
    buyer_name: str | None
    available_on: date
    published_on: date | None
    deadline_on: date | None
    awarded_on: date | None
    contract_end_on: date | None
    framework: bool
    estimated_value_eur: int | None
    award_value_eur: int | None
    offers: int | None
    winner_name: str | None
    url: str | None


class FeatureValue(BaseModel):
    name: str
    value: float


class MunicipalityForecast(BaseModel):
    ags: str
    name: str
    population: int | None
    area_km2: float | None
    model: ModelSummary | None
    as_of: date | None
    rank: int | None  # among all municipalities scored that day
    total: int
    score: float | None
    reasons: list[ReasonRead]
    features: list[FeatureValue]  # what the model saw on the day
    history: list[ScorePoint]  # oldest first
    signals: list[SignalRead]  # newest first
    tenders: list[TenderRead]  # newest first


class ModelRead(BaseModel):
    id: uuid.UUID
    version: str
    kind: ModelKind
    horizon_months: int
    active: bool
    trained_until: date | None
    trained_at: datetime | None
    trained_by: str | None
    metrics: Mapping[str, JSONValue]
    created_at: datetime
