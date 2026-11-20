"""The forecast API: where the next heat network is likely put out to tender, and why.

Signed-in users read the ranking and a municipality's file: its score over time, the reasons, the
signals and tenders it rests on. Admins see the models and choose the one that serves.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from sqlmodel import col, select

from infrasales.audit import service as audit
from infrasales.auth.deps import AdminUser, CurrentUser
from infrasales.core.db import Session
from infrasales.core.models import utcnow
from infrasales.forecast import service
from infrasales.forecast.features import FEATURES, features
from infrasales.forecast.models import ForecastModel, Prediction
from infrasales.forecast.schemas import (
    FeatureValue,
    ModelRead,
    ModelSummary,
    MunicipalityForecast,
    RankedMunicipality,
    Ranking,
    RankingQuery,
    ReasonRead,
    ScorePoint,
    SignalRead,
    TenderRead,
)
from infrasales.jobs.names import JobName
from infrasales.projects.models import Municipality, Signal, Tender
from infrasales.scheduler import runs
from infrasales.scheduler.worker import WORKER

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


def _reasons(prediction: Prediction) -> list[ReasonRead]:
    return [ReasonRead.model_validate(reason) for reason in prediction.reasons]


@router.get("/municipalities")
async def read_ranking(
    query: Annotated[RankingQuery, Query()], _: CurrentUser, session: Session
) -> Ranking:
    """The municipalities most likely to put a heat network's construction out to tender first.

    Scored by the active model on its latest day, in a region if asked (an AGS prefix). No
    day yet: the model has not run since it was activated.
    """
    model = await service.active_model(session)
    if model is None:
        return Ranking(model=None, as_of=None, total=0, items=[])
    as_of = await service.latest_day(session, model)
    if as_of is None:  # activated, its first run still to come
        return Ranking(model=ModelSummary.of(model), as_of=None, total=0, items=[])
    total, page = await service.ranking(
        session, model, as_of, region=query.region, limit=query.limit, offset=query.offset
    )
    items = [
        RankedMunicipality(
            rank=ranked.rank,
            ags=ranked.municipality.ags,
            name=ranked.municipality.name,
            population=ranked.municipality.population,
            score=ranked.prediction.score,
            reasons=_reasons(ranked.prediction),
        )
        for ranked in page
    ]
    return Ranking(model=ModelSummary.of(model), as_of=as_of, total=total, items=items)


@router.get("/municipalities/{ags}", responses={404: {"description": "No such municipality"}})
async def read_municipality(ags: str, _: CurrentUser, session: Session) -> MunicipalityForecast:
    """A municipality's forecast file: score, rank, reasons, the features and evidence behind it."""
    place = (await session.exec(select(Municipality).where(Municipality.ags == ags))).first()
    if place is None:
        raise HTTPException(404, "No such municipality")
    model = await service.active_model(session)
    as_of = await service.latest_day(session, model) if model else None
    scores = list(await service.scores_of(session, model, ags)) if model else []
    current = next((p for p in scores if p.as_of == as_of), None)
    rank, total = (None, 0)
    if model and as_of and current:
        rank, total = await service.rank_of(session, model, current)
    signals = await session.exec(
        select(Signal)
        .where(col(Signal.municipality_ags) == ags)
        .order_by(col(Signal.available_on).desc())
    )
    tenders = await session.exec(
        select(Tender)
        .where(col(Tender.municipality_ags) == ags, col(Tender.heat_network))
        .order_by(col(Tender.available_on).desc())
    )
    seen: list[FeatureValue] = []
    if as_of is not None:
        history = await service.load_history(session, only=ags)
        values = features(history, ags, as_of)
        seen = [FeatureValue(name=n, value=v) for n, v in zip(FEATURES, values, strict=True)]
    return MunicipalityForecast(
        ags=place.ags,
        name=place.name,
        population=place.population,
        area_km2=place.area_km2,
        model=ModelSummary.of(model) if model else None,
        as_of=as_of,
        rank=rank,
        total=total,
        score=current.score if current else None,
        reasons=_reasons(current) if current else [],
        features=seen,
        history=[ScorePoint(as_of=p.as_of, score=p.score) for p in scores],
        signals=[SignalRead.model_validate(s, from_attributes=True) for s in signals],
        tenders=[TenderRead.model_validate(t, from_attributes=True) for t in tenders],
    )


@router.get("/models")
async def list_models(_: AdminUser, session: Session) -> list[ModelRead]:
    """Every version of the forecast model, newest first, with its backtest (admins only)."""
    return [
        ModelRead.model_validate(m, from_attributes=True) for m in await service.models(session)
    ]


@router.post("/models/{model_id}/activate", responses={404: {"description": "No such model"}})
async def activate_model(
    model_id: UUID, admin: AdminUser, session: Session, request: Request, tasks: BackgroundTasks
) -> ModelRead:
    """Serve the forecast with this model (admins only): a forecast run is queued at once."""
    model = await session.get(ForecastModel, model_id)
    if model is None:
        raise HTTPException(404, "No such model")
    if not model.active:
        await service.activate(session, model)
        audit.record(
            session,
            actor=admin.subject,
            action="forecast.model_activated",
            target=model.version,
            request=request,
        )
        await runs.enqueue(session, JobName.FORECAST, utcnow(), triggered_by=admin.subject)
        if worker := WORKER.find(request):
            tasks.add_task(worker.wake)  # after the commit, so the worker finds the run
    return ModelRead.model_validate(model, from_attributes=True)
