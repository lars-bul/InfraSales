from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date

import pytest
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.projects.models import (
    Municipality,
    PostCode,
    Tender,
    TenderAward,
    TenderKind,
    TenderStatus,
)
from infrasales.sources.heat import Relevance
from infrasales.sources.records import AwardRecord, LotRecord
from infrasales.sources.store import resolver, store

pytestmark = pytest.mark.anyio

NETWORK = Relevance(heat_network=True, reason="words:title")


def lot(**values: object) -> LotRecord:
    base = LotRecord(
        source="ted",
        notice_id="100-2025",
        notice_type="cn-standard",
        procedure_ref="p-1",
        lot="LOT-0001",
        title="Wärmenetz Bahnstadt",
        kind=TenderKind.CONSTRUCTION,
        status=TenderStatus.PUBLISHED,
        published_on=date(2025, 3, 1),
        relevance=NETWORK,
        cpv=("45232140",),
        buyer_name="Stadtwerke Heidelberg GmbH",
        place_post_code="69117",
        deadline_on=date(2025, 4, 1),
    )
    return replace(base, **values)


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    async with db.session() as session:
        session.add_all(
            [
                Municipality(ags="08221000", name="Heidelberg, Stadt"),
                Municipality(ags="08226095", name="Walldorf, Stadt"),
            ]
        )
        session.add(
            PostCode(
                post_code="69117", locality="Heidelberg", municipality_ags="08221000", streets=9
            )
        )
    yield db
    await db.dispose()


async def stored(db: Database) -> list[Tender]:
    async with db.session() as session:
        return list((await session.exec(select(Tender))).all())


async def test_a_procedures_notices_from_both_sources_become_one_tender(db: Database) -> None:
    call = lot()
    award = lot(
        source="doe",
        notice_id="uuid-9",
        notice_type="can-standard",
        status=TenderStatus.AWARDED,
        published_on=date(2025, 6, 1),
        offers=4,
        awarded_on=date(2025, 5, 20),
        awards=(
            AwardRecord("Tiefbau Neckar GmbH", post_code="69117", city="Heidelberg", size="small"),
        ),
    )
    async with db.session() as session:
        first = await store(session, [award, call], await resolver(session))
    (tender,) = await stored(db)
    async with db.session() as session:
        awards = (await session.exec(select(TenderAward))).all()

    assert (first.tenders_new, first.awards_new, first.skipped) == (1, 1, 0)
    assert (tender.ref, tender.status, tender.source) == (
        "proc:p-1:LOT-0001",
        TenderStatus.AWARDED,
        "ted+doe",
    )
    assert (tender.published_on, tender.available_on, tender.offers) == (
        date(2025, 3, 1),
        date(2025, 3, 1),
        4,
    )
    assert tender.municipality_ags == "08221000"
    assert [(a.winner_name, a.winner_ags, a.winner_size) for a in awards] == [
        ("Tiefbau Neckar GmbH", "08221000", "small")
    ]


async def test_loading_again_updates_and_keeps_one_award_per_winner(db: Database) -> None:
    award = lot(status=TenderStatus.AWARDED, awards=(AwardRecord("Tiefbau Neckar GmbH"),))
    async with db.session() as session:
        await store(session, [award], await resolver(session))
    async with db.session() as session:
        again = await store(session, [award], await resolver(session))

    assert (again.tenders_new, again.tenders_updated, again.awards_new) == (0, 1, 0)


async def test_a_lot_that_is_no_heat_network_is_not_kept(db: Database) -> None:
    async with db.session() as session:
        result = await store(
            session,
            [lot(relevance=Relevance(heat_network=False, reason="no-network"))],
            await resolver(session),
        )

    assert result.skipped == 1
    assert await stored(db) == []


async def test_a_buyer_named_after_its_town_places_a_tender_without_an_address(
    db: Database,
) -> None:
    async with db.session() as session:
        await store(
            session,
            [lot(place_post_code=None, buyer_name="Stadt Walldorf", place_nuts="DE128")],
            await resolver(session),
        )

    (tender,) = await stored(db)
    assert tender.municipality_ags == "08226095"


async def test_an_award_known_only_from_its_notice_counts_as_put_out_then(db: Database) -> None:
    async with db.session() as session:
        await store(
            session,
            [lot(procedure_ref=None, status=TenderStatus.AWARDED, published_on=date(2025, 7, 1))],
            await resolver(session),
        )

    (tender,) = await stored(db)
    assert (tender.ref, tender.published_on) == ("ted:100-2025:LOT-0001", date(2025, 7, 1))


async def test_a_pipeline_award_of_another_medium_is_kept_for_the_market_only(db: Database) -> None:
    water = Relevance(heat_network=False, reason="pipeline")
    award = lot(
        relevance=water, status=TenderStatus.AWARDED, awards=(AwardRecord("Leitungsbau Süd GmbH"),)
    )
    call = lot(procedure_ref="p-2", relevance=water)
    async with db.session() as session:
        result = await store(session, [award, call], await resolver(session))

    (tender,) = await stored(db)
    assert (result.tenders_new, result.skipped) == (1, 1)
    assert (tender.heat_network, tender.relevance) == (False, "pipeline")


async def test_a_heat_network_notice_makes_its_procedure_one(db: Database) -> None:
    water = lot(
        relevance=Relevance(heat_network=False, reason="pipeline"),
        status=TenderStatus.AWARDED,
        awards=(AwardRecord("A"),),
    )
    async with db.session() as session:
        await store(session, [water, lot(published_on=date(2025, 1, 1))], await resolver(session))

    (tender,) = await stored(db)
    assert (tender.heat_network, tender.relevance) == (True, "words:title")
