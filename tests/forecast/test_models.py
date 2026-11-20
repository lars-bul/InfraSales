from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy import exc
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.forecast.models import ForecastModel, ModelKind, Prediction
from infrasales.projects.models import Municipality

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    async with db.session() as session:
        session.add(Municipality(ags="08221000", name="Heidelberg"))
    yield db
    await db.dispose()


def a_model(version: str = "heuristic-1") -> ForecastModel:
    return ForecastModel(
        name="heat-network-construction",
        version=version,
        kind=ModelKind.HEURISTIC,
        horizon_months=24,
        features=["log_population"],
        parameters={"weights": {"log_population": 0.25}, "bias": -7.0},
    )


async def test_a_model_starts_inactive_and_untrained(db: Database) -> None:
    async with db.session() as session:
        session.add(a_model())

    async with db.session() as session:
        stored = (await session.exec(select(ForecastModel))).one()

    assert (stored.active, stored.trained_at, stored.metrics) == (False, None, {})
    assert stored.parameters == {"weights": {"log_population": 0.25}, "bias": -7.0}


async def test_a_models_version_is_unique_per_name(db: Database) -> None:
    async with db.session() as session:
        session.add(a_model())

    with pytest.raises(exc.IntegrityError):
        async with db.session() as session:
            session.add(a_model())


async def test_a_municipality_has_one_prediction_per_model_and_day(db: Database) -> None:
    model = a_model()
    async with db.session() as session:
        session.add(model)
        await session.flush()
        session.add(
            Prediction(
                model_id=model.id, municipality_ags="08221000", as_of=date(2026, 1, 1), score=0.2
            )
        )

    with pytest.raises(exc.IntegrityError):
        async with db.session() as session:
            session.add(
                Prediction(
                    model_id=model.id,
                    municipality_ags="08221000",
                    as_of=date(2026, 1, 1),
                    score=0.3,
                )
            )


async def test_deleting_a_model_deletes_its_predictions(db: Database) -> None:
    model = a_model()
    async with db.session() as session:
        session.add(model)
        await session.flush()
        session.add(
            Prediction(
                model_id=model.id,
                municipality_ags="08221000",
                as_of=date(2026, 1, 1),
                score=0.2,
                reasons=[{"feature": "x"}],
            )
        )

    async with db.session() as session:
        await session.delete(await session.get_one(ForecastModel, model.id))

    async with db.session() as session:
        assert (await session.exec(select(Prediction))).all() == []
