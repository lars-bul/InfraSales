from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import exc
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.projects.ids import new_public_id
from infrasales.projects.models import (
    Actor,
    ActorKind,
    ActorRole,
    Claim,
    ClaimState,
    Municipality,
    Origin,
    Phase,
    Project,
    ProjectActor,
    ProjectEvent,
    Publication,
    Sector,
)

pytestmark = pytest.mark.anyio

KNOWN = datetime(2026, 3, 2, 9, 30, tzinfo=UTC)


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


async def a_project(db: Database) -> Project:
    project = Project(
        public_id=new_public_id(),
        sector=Sector.HEAT_NETWORK,
        title="Wärmenetz Weststadt",
        municipality_ags="08221000",
    )
    async with db.session() as session:
        session.add(Municipality(ags="08221000", name="Heidelberg", population=162_000))
        await session.flush()
        session.add(project)
    return project


async def test_a_project_starts_as_an_unpublished_draft_with_no_facts(db: Database) -> None:
    await a_project(db)

    async with db.session() as session:
        stored = (await session.exec(select(Project))).one()

    assert (stored.publication, stored.phase, stored.facts) == (Publication.DRAFT, None, {})
    assert (stored.sector, stored.municipality_ags) == (Sector.HEAT_NETWORK, "08221000")


async def test_a_public_id_is_never_given_out_twice(db: Database) -> None:
    project = await a_project(db)
    twin = Project(
        public_id=project.public_id,
        sector=Sector.HEAT_NETWORK,
        title="Another",
        municipality_ags="08221000",
    )

    with pytest.raises(exc.IntegrityError):
        async with db.session() as session:
            session.add(twin)


async def test_a_claim_keeps_its_value_evidence_and_origin(db: Database) -> None:
    project = await a_project(db)
    claim = Claim(
        project_id=project.id,
        field="trench_length_km",
        value=4.2,
        page=37,
        quote="Die Trassenlänge des ersten Bauabschnitts beträgt rund 4,2 km.",
        quote_found=True,
        origin=Origin.MODEL,
        origin_detail="example/model-1",
    )
    async with db.session() as session:
        session.add(claim)

    async with db.session() as session:
        stored = (await session.exec(select(Claim))).one()

    assert (stored.value, stored.page, stored.quote_found) == (4.2, 37, True)
    assert (stored.origin, stored.state) == (Origin.MODEL, ClaimState.PENDING)


async def test_a_status_event_knows_when_it_happened_and_since_when_we_know(
    db: Database,
) -> None:
    project = await a_project(db)
    claim = Claim(project_id=project.id, field="phase", value="decision", origin=Origin.MODEL)
    async with db.session() as session:
        session.add(claim)
        await session.flush()
        session.add(
            ProjectEvent(
                project_id=project.id,
                phase=Phase.DECISION,
                occurred_on=date(2026, 2, 26),
                known_since=KNOWN,
                claim_id=claim.id,
            )
        )

    async with db.session() as session:
        event = (await session.exec(select(ProjectEvent))).one()

    assert (event.phase, event.occurred_on, event.known_since) == (
        Phase.DECISION,
        date(2026, 2, 26),
        KNOWN,
    )


async def test_an_actor_has_each_role_in_a_project_once(db: Database) -> None:
    project = await a_project(db)
    actor = Actor(name="Stadtwerke Heidelberg", kind=ActorKind.UTILITY, seat_ags="08221000")
    async with db.session() as session:
        session.add(actor)
        await session.flush()
        session.add(ProjectActor(project_id=project.id, actor_id=actor.id, role=ActorRole.OWNER))

    with pytest.raises(exc.IntegrityError):
        async with db.session() as session:
            session.add(
                ProjectActor(project_id=project.id, actor_id=actor.id, role=ActorRole.OWNER)
            )


async def test_a_merged_project_points_at_the_one_it_became(db: Database) -> None:
    kept = await a_project(db)
    merged = Project(
        public_id=new_public_id(),
        sector=Sector.HEAT_NETWORK,
        title="Nahwärme Weststadt",
        municipality_ags="08221000",
        merged_into_id=kept.id,
    )
    async with db.session() as session:
        session.add(merged)

    async with db.session() as session:
        stored = await session.get(Project, merged.id)

    assert stored is not None
    assert stored.merged_into_id == kept.id
