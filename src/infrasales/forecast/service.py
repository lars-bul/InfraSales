"""The forecast in the database: the public history it reads, its models and its predictions.

One model of a name is active; it serves the ranking. The heuristic is stored on first use, so a
fresh installation ranks from its first imported signals. A learned model is stored inactive and
activated by a person once its backtest beats the active one (`infrasales forecast-train`).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import ColumnElement, and_, func, or_, true
from sqlmodel import col, delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.core.models import JSONValue, utcnow
from infrasales.forecast import heuristic
from infrasales.forecast.features import (
    FEATURES,
    HORIZON_MONTHS,
    History,
    MetricFact,
    Place,
    SignalFact,
    TenderFact,
    features,
)
from infrasales.forecast.heuristic import Heuristic
from infrasales.forecast.logistic import Logistic
from infrasales.forecast.models import ForecastModel, ModelKind, Prediction
from infrasales.forecast.scoring import Scorer, mean_vector
from infrasales.projects.models import (
    Municipality,
    MunicipalityMetric,
    Sector,
    Signal,
    Tender,
)

MODEL_NAME = "heat-network-construction"


async def load_history(session: AsyncSession, only: str | None = None) -> History:
    """Every municipality (or `only` that one), with its signals, heat network tenders, metrics."""
    places = [
        Place(m.ags, m.name, m.population, m.area_km2)
        for m in await session.exec(select(Municipality).where(_of(Municipality.ags, only)))
    ]
    signals = [
        (s.municipality_ags, SignalFact(s.kind, s.available_on, s.occurred_on))
        for s in await session.exec(select(Signal).where(_of(Signal.municipality_ags, only)))
    ]
    tenders = [
        (
            t.municipality_ags,
            TenderFact(
                t.kind,
                t.origin,
                t.status,
                t.available_on,
                t.published_on,
                t.framework,
                t.contract_end_on,
            ),
        )
        for t in await session.exec(
            select(Tender).where(
                col(Tender.sector) == Sector.HEAT_NETWORK,
                col(Tender.heat_network),
                col(Tender.municipality_ags).is_not(None),
                _of(Tender.municipality_ags, only),
            )
        )
        if t.municipality_ags is not None
    ]
    metrics = [
        (m.municipality_ags, MetricFact(m.metric, m.available_on, m.value))
        for m in await session.exec(
            select(MunicipalityMetric).where(_of(MunicipalityMetric.municipality_ags, only))
        )
    ]
    return History.of(places, signals, tenders, metrics)


def _of(column: str | None, ags: str | None) -> ColumnElement[bool]:
    """Every row, or only those of `ags`."""
    return true() if ags is None else col(column) == ags


async def active_model(session: AsyncSession, name: str = MODEL_NAME) -> ForecastModel | None:
    statement = select(ForecastModel).where(
        col(ForecastModel.name) == name, col(ForecastModel.active)
    )
    return (await session.exec(statement)).first()


async def ensure_heuristic(session: AsyncSession, name: str = MODEL_NAME) -> ForecastModel:
    """The active model; the heuristic, stored and activated, while there is none."""
    if model := await active_model(session, name):
        return model
    stored = (
        await session.exec(
            select(ForecastModel).where(
                col(ForecastModel.name) == name, col(ForecastModel.version) == heuristic.VERSION
            )
        )
    ).first()
    if stored is None:
        rule = Heuristic.default()
        stored = ForecastModel(
            name=name,
            version=heuristic.VERSION,
            kind=ModelKind.HEURISTIC,
            horizon_months=HORIZON_MONTHS,
            features=list(rule.features),
            parameters=rule.parameters(),
        )
    stored.active = True
    session.add(stored)
    await session.flush()
    return stored


def scorer(model: ForecastModel) -> Scorer:
    """What scores with the stored model's parameters."""
    if model.kind is ModelKind.HEURISTIC:
        return Heuristic.from_parameters(model.features, model.parameters)
    return Logistic.from_parameters(model.features, model.parameters)


async def store_learned(  # noqa: PLR0913  # what was learned, and how it did
    session: AsyncSession,
    model: Logistic,
    *,
    horizon_months: int,
    trained_until: date,
    metrics: dict[str, JSONValue],
    by: str | None,
    name: str = MODEL_NAME,
) -> ForecastModel:
    """A learned model, stored inactive: activating it is a person's decision (`activate`)."""
    stored = ForecastModel(
        name=name,
        version=f"logistic-{trained_until.isoformat()}-{uuid.uuid4().hex[:6]}",
        kind=ModelKind.LOGISTIC,
        horizon_months=horizon_months,
        features=list(model.features),
        parameters=model.parameters(),
        metrics=metrics,
        trained_until=trained_until,
        trained_at=utcnow(),
        trained_by=by,
    )
    session.add(stored)
    await session.flush()
    return stored


async def activate(session: AsyncSession, model: ForecastModel) -> None:
    """Make `model` the one serving its name's predictions."""
    await session.exec(
        update(ForecastModel)
        .where(col(ForecastModel.name) == model.name, col(ForecastModel.id) != model.id)
        .values(active=False)
    )
    model.active = True
    session.add(model)
    await session.flush()


async def models(session: AsyncSession, name: str = MODEL_NAME) -> Sequence[ForecastModel]:
    statement = (
        select(ForecastModel)
        .where(col(ForecastModel.name) == name)
        .order_by(col(ForecastModel.created_at).desc())
    )
    return (await session.exec(statement)).all()


async def predict(
    session: AsyncSession,
    model: ForecastModel,
    history: History,
    as_of: date,
    run_id: uuid.UUID | None = None,
) -> int:
    """Score every municipality on `as_of` with what was known by then; replaces earlier scores.

    Reasons are measured against the mean municipality of the day: what sets this one apart.
    """
    rule = scorer(model)
    if tuple(model.features) != FEATURES:
        msg = f"model {model.version} has other features than this code computes"
        raise ValueError(msg)
    rows = {ags: features(history, ags, as_of) for ags in sorted(history.places)}
    baseline = mean_vector(list(rows.values()), len(FEATURES))
    await session.exec(
        delete(Prediction).where(
            col(Prediction.model_id) == model.id, col(Prediction.as_of) == as_of
        )
    )
    session.add_all(
        Prediction(
            model_id=model.id,
            municipality_ags=ags,
            as_of=as_of,
            score=rule.score(x),
            reasons=[reason.as_json() for reason in rule.reasons(x, baseline)],
            run_id=run_id,
        )
        for ags, x in rows.items()
    )
    await session.flush()
    return len(rows)


async def latest_day(session: AsyncSession, model: ForecastModel) -> date | None:
    """The day of the model's newest predictions."""
    statement = select(func.max(col(Prediction.as_of))).where(col(Prediction.model_id) == model.id)
    return (await session.exec(statement)).first()


@dataclass(frozen=True, slots=True)
class Ranked:
    rank: int
    prediction: Prediction
    municipality: Municipality


async def ranking(  # noqa: PLR0913  # the model, the day and the page asked for
    session: AsyncSession,
    model: ForecastModel,
    as_of: date,
    *,
    region: str = "",
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[Ranked]]:
    """The municipalities best scored first, in a region (an AGS prefix): how many, and a page."""
    where = (
        col(Prediction.model_id) == model.id,
        col(Prediction.as_of) == as_of,
        col(Prediction.municipality_ags).startswith(region),
    )
    total = (await session.exec(select(func.count()).select_from(Prediction).where(*where))).one()
    statement = (
        select(Prediction, Municipality)
        .join(Municipality, col(Municipality.ags) == col(Prediction.municipality_ags))
        .where(*where)
        .order_by(col(Prediction.score).desc(), col(Municipality.ags))
        .offset(offset)
        .limit(limit)
    )
    page = (await session.exec(statement)).all()
    return total, [
        Ranked(offset + i + 1, prediction, municipality)
        for i, (prediction, municipality) in enumerate(page)
    ]


async def rank_of(
    session: AsyncSession, model: ForecastModel, prediction: Prediction
) -> tuple[int, int]:
    """Where a prediction ranks among its day's, in the ranking's order, and out of how many."""
    day = (col(Prediction.model_id) == model.id, col(Prediction.as_of) == prediction.as_of)
    ahead = or_(
        col(Prediction.score) > prediction.score,
        and_(
            col(Prediction.score) == prediction.score,
            col(Prediction.municipality_ags) < prediction.municipality_ags,
        ),
    )
    count = select(func.count()).select_from(Prediction)
    before = (await session.exec(count.where(*day, ahead))).one()
    total = (await session.exec(count.where(*day))).one()
    return before + 1, total


async def scores_of(session: AsyncSession, model: ForecastModel, ags: str) -> Sequence[Prediction]:
    """The model's predictions for one municipality, oldest first: how its score developed."""
    statement = (
        select(Prediction)
        .where(col(Prediction.model_id) == model.id, col(Prediction.municipality_ags) == ags)
        .order_by(col(Prediction.as_of))
    )
    return (await session.exec(statement)).all()
