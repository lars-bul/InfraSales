"""Forecast models and their predictions: where the next heat network is put out to tender.

A model is stored with what it was trained on and how it did in its backtest; every prediction
names its model, the municipality, the day it is for and why (its strongest reasons). Modell A of
ADR 06 §4: it learns from public data on the demand side only.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from infrasales.core.models import (
    SUBJECT_LENGTH,
    BaseTable,
    JSONType,
    JSONValue,
    UTCDateTime,
    enum_type,
)
from infrasales.projects.models import AGS_LENGTH


class ModelKind(StrEnum):
    HEURISTIC = "heuristic"  # weights set by hand: the start, before there is data to learn from
    LOGISTIC = "logistic"  # weights learned: a discrete-time hazard model (`forecast.logistic`)
    CHOICE = "choice"  # who wins: a conditional logit over the market (`forecast.winners`)


class ForecastModel(BaseTable, table=True):
    """One version of a forecast model; one of a name is active and serves the predictions."""

    __table_args__ = (UniqueConstraint("name", "version"),)

    name: str = Field(max_length=64)  # what it forecasts, e.g. "heat-network-construction"
    version: str = Field(max_length=64)
    kind: ModelKind = Field(sa_type=enum_type(ModelKind))
    horizon_months: int = Field(gt=0)  # a tender within this many months counts
    features: list[str] = Field(default_factory=list[str], sa_type=JSONType)
    parameters: dict[str, JSONValue] = Field(default_factory=dict[str, JSONValue], sa_type=JSONType)
    metrics: dict[str, JSONValue] = Field(default_factory=dict[str, JSONValue], sa_type=JSONType)
    trained_until: date | None = None  # the last day its training labels cover
    trained_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    trained_by: str | None = Field(default=None, max_length=SUBJECT_LENGTH)
    active: bool = Field(default=False, index=True)


class Prediction(BaseTable, table=True):
    """How likely a municipality puts a heat network's construction out to tender, and why."""

    __table_args__ = (
        UniqueConstraint("model_id", "municipality_ags", "as_of"),
        Index("ix_prediction_model_id_as_of_score", "model_id", "as_of", "score"),
    )

    model_id: uuid.UUID = Field(foreign_key="forecast_model.id", ondelete="CASCADE")
    municipality_ags: str = Field(foreign_key="municipality.ags", max_length=AGS_LENGTH)
    as_of: date  # what was known by this day went in
    score: float  # a probability for a learned model; a relative score for a heuristic one
    reasons: list[JSONValue] = Field(default_factory=list[JSONValue], sa_type=JSONType)
    # The run that made it; job runs are pruned long before predictions, which then keep NULL.
    run_id: uuid.UUID | None = Field(
        default=None, foreign_key="job_run.id", ondelete="SET NULL", index=True
    )
