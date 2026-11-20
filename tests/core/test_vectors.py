import math
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, insert, select

from infrasales.core.db import Database
from infrasales.core.vectors import Vector, cosine_distance, unit, vector

pytestmark = pytest.mark.anyio

METADATA = MetaData()
POINTS = Table(
    "test_vector_point",
    METADATA,
    Column("id", Integer, primary_key=True),
    Column("embedding", Vector(3)),
)


@pytest.fixture
async def points(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    async with db.engine.begin() as connection:
        await connection.run_sync(METADATA.create_all)
    yield db
    async with db.engine.begin() as connection:
        await connection.run_sync(METADATA.drop_all)
    await db.dispose()


async def test_vectors_round_trip_and_the_nearest_comes_first(points: Database) -> None:
    async with points.engine.begin() as connection:
        await connection.execute(
            insert(POINTS),
            [
                {"id": 1, "embedding": [1.0, 0.0, 0.0]},
                {"id": 2, "embedding": [0.0, 1.0, 0.0]},
                {"id": 3, "embedding": None},
            ],
        )
        distance = cosine_distance(POINTS.c.embedding, vector([0.8, 0.6, 0.0], 3))
        ranked = (
            await connection.execute(
                select(POINTS.c.id, distance)
                .where(POINTS.c.embedding.is_not(None))
                .order_by(distance)
            )
        ).all()
        stored = (
            await connection.execute(select(POINTS.c.embedding).where(POINTS.c.id == 2))
        ).scalar()

    assert [row[0] for row in ranked] == [1, 2]
    assert [round(row[1], 3) for row in ranked] == [0.2, 0.4]
    assert stored == [0.0, 1.0, 0.0]


def test_a_unit_vector_keeps_the_first_dimensions_and_has_length_one() -> None:
    shortened = unit([3.0, 4.0, 12.0], 2)

    assert shortened == [0.6, 0.8]
    assert math.isclose(sum(value * value for value in shortened), 1.0)


def test_a_zero_vector_stays_zero() -> None:
    assert unit([0.0, 0.0], 2) == [0.0, 0.0]
