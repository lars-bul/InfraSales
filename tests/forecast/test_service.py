from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.forecast import heuristic, service
from infrasales.forecast.features import FEATURES
from infrasales.forecast.heuristic import Heuristic
from infrasales.forecast.logistic import Logistic
from infrasales.forecast.models import ForecastModel, ModelKind, Prediction
from infrasales.projects.models import (
    MetricKind,
    Municipality,
    MunicipalityMetric,
    Signal,
    SignalKind,
    Tender,
    TenderKind,
    TenderOrigin,
    TenderStatus,
)

pytestmark = pytest.mark.anyio

AS_OF = date(2026, 1, 1)


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    async with db.session() as session:
        session.add_all(
            [
                Municipality(ags="08221000", name="Heidelberg", population=162_000, area_km2=108.8),
                Municipality(ags="08421000", name="Ulm", population=128_000, area_km2=118.7),
                Municipality(ags="09162000", name="München", population=1_500_000),
            ]
        )
        await session.flush()
        session.add_all(
            [
                Signal(
                    kind=SignalKind.COUNCIL_DECISION,
                    municipality_ags="08221000",
                    available_on=date(2025, 6, 1),
                    ref="test:council",
                ),
                Signal(
                    kind=SignalKind.FUNDING_GRANTED,
                    municipality_ags="08221000",
                    available_on=date(2025, 9, 1),
                    ref="test:funding",
                ),
                Tender(
                    origin=TenderOrigin.NOTICE,
                    ref="ted:1",
                    kind=TenderKind.CONSTRUCTION,
                    status=TenderStatus.AWARDED,
                    title="Wärmenetz Ulm",
                    municipality_ags="08421000",
                    available_on=date(2024, 3, 1),
                    published_on=date(2024, 3, 1),
                ),
                Tender(  # no municipality: not part of anyone's history
                    origin=TenderOrigin.NOTICE,
                    ref="ted:2",
                    kind=TenderKind.CONSTRUCTION,
                    status=TenderStatus.PUBLISHED,
                    title="Fernwärme irgendwo",
                    available_on=date(2024, 3, 1),
                ),
                MunicipalityMetric(
                    municipality_ags="08421000",
                    metric=MetricKind.DISTRICT_HEATING_SHARE,
                    as_of=date(2022, 5, 15),
                    available_on=date(2024, 6, 1),
                    value=0.1,
                    source="zensus-2022",
                ),
            ]
        )
    yield db
    await db.dispose()


async def test_the_history_holds_every_municipality_and_its_public_facts(db: Database) -> None:
    async with db.session() as session:
        history = await service.load_history(session)

    assert sorted(history.places) == ["08221000", "08421000", "09162000"]
    assert [s.kind for s in history.signals["08221000"]] == [
        SignalKind.COUNCIL_DECISION,
        SignalKind.FUNDING_GRANTED,
    ]
    assert [t.published_on for t in history.tenders["08421000"]] == [date(2024, 3, 1)]
    assert [m.value for m in history.metrics["08421000"]] == [0.1]
    assert history.places["08221000"].area_km2 == 108.8


async def test_the_heuristic_is_stored_and_activated_once(db: Database) -> None:
    async with db.session() as session:
        first = await service.ensure_heuristic(session)
    async with db.session() as session:
        again = await service.ensure_heuristic(session)
        stored = (await session.exec(select(ForecastModel))).all()

    assert first.id == again.id
    assert (first.version, first.kind, first.active) == (
        heuristic.VERSION,
        ModelKind.HEURISTIC,
        True,
    )
    assert len(stored) == 1


async def test_an_inactive_heuristic_is_activated_again_while_no_model_is(db: Database) -> None:
    async with db.session() as session:
        model = await service.ensure_heuristic(session)
        model.active = False
    async with db.session() as session:
        again = await service.ensure_heuristic(session)

    assert (again.id, again.active) == (model.id, True)


async def test_predictions_rank_the_municipality_with_signals_first(db: Database) -> None:
    async with db.session() as session:
        model = await service.ensure_heuristic(session)
        history = await service.load_history(session)
        made = await service.predict(session, model, history, AS_OF)
    async with db.session() as session:
        total, page = await service.ranking(session, model, AS_OF, limit=2)

    assert (made, total) == (3, 3)
    assert [r.rank for r in page] == [1, 2]
    assert page[0].municipality.name == "Heidelberg"
    first = page[0].prediction.reasons[0]
    assert isinstance(first, dict)
    assert first["feature"] in {"recent_council_decision", "recent_funding_granted"}


async def test_the_ranking_is_filtered_by_region_and_paged(db: Database) -> None:
    async with db.session() as session:
        model = await service.ensure_heuristic(session)
        await service.predict(session, model, await service.load_history(session), AS_OF)
    async with db.session() as session:
        total, page = await service.ranking(session, model, AS_OF, region="08", limit=1, offset=1)

    assert total == 2
    assert [(r.rank, r.municipality.ags) for r in page] == [(2, "08421000")]


async def test_predicting_a_day_again_replaces_its_predictions(db: Database) -> None:
    async with db.session() as session:
        model = await service.ensure_heuristic(session)
        history = await service.load_history(session)
        await service.predict(session, model, history, AS_OF)
        await service.predict(session, model, history, AS_OF)
        await service.predict(session, model, history, date(2026, 4, 1))
    async with db.session() as session:
        rows = (await session.exec(select(Prediction))).all()
        latest = await service.latest_day(session, model)
        heidelberg = await service.scores_of(session, model, "08221000")

    assert len(rows) == 6
    assert latest == date(2026, 4, 1)
    assert [p.as_of for p in heidelberg] == [AS_OF, date(2026, 4, 1)]


async def test_a_model_with_other_features_does_not_predict(db: Database) -> None:
    async with db.session() as session:
        model = await service.ensure_heuristic(session)
        model.features = ["log_population"]
        model.parameters = {"weights": {"log_population": 1.0}, "bias": 0.0}
        with pytest.raises(ValueError, match="other features"):
            await service.predict(session, model, await service.load_history(session), AS_OF)


async def test_a_learned_model_is_stored_inactive_until_activated(db: Database) -> None:
    learned = Logistic(
        FEATURES,
        tuple(0.0 for _ in FEATURES),
        tuple(1.0 for _ in FEATURES),
        tuple(0.1 for _ in FEATURES),
        -3.0,
    )
    async with db.session() as session:
        rule = await service.ensure_heuristic(session)
        stored = await service.store_learned(
            session,
            learned,
            horizon_months=24,
            trained_until=AS_OF,
            metrics={"roc_auc": 0.8},
            by="cli",
        )
        active_before = await service.active_model(session)
        await service.activate(session, stored)
    async with db.session() as session:
        active = await service.active_model(session)
        listed = await service.models(session)

    assert active_before is not None
    assert active_before.id == rule.id
    assert stored.version.startswith("logistic-2026-01-01-")
    assert active is not None
    assert active.id == stored.id
    assert service.scorer(active) == learned
    assert {m.version: m.active for m in listed} == {heuristic.VERSION: False, stored.version: True}


async def test_a_stored_heuristic_scores_as_the_default_one(db: Database) -> None:
    async with db.session() as session:
        model = await service.ensure_heuristic(session)

    assert service.scorer(model) == Heuristic.default()
