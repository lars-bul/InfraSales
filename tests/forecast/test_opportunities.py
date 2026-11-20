from collections.abc import AsyncIterator
from datetime import date

import pytest

from infrasales.core.db import Database
from infrasales.forecast import opportunities, service
from infrasales.forecast.winners import WinModel
from infrasales.projects.models import (
    Municipality,
    PostCode,
    Tender,
    TenderAward,
    TenderKind,
    TenderOrigin,
    TenderStatus,
)
from infrasales.tenancy import service as tenancy
from infrasales.tenancy.models import Bid, BidOutcome, Tenant

pytestmark = pytest.mark.anyio
TODAY = date(2026, 3, 1)


def tender(ref: str, ags: str, status: TenderStatus, **values: object) -> Tender:
    base: dict[str, object] = {
        "origin": TenderOrigin.NOTICE,
        "ref": ref,
        "kind": TenderKind.CONSTRUCTION,
        "status": status,
        "title": f"Wärmenetz {ref}",
        "municipality_ags": ags,
        "available_on": date(2025, 1, 1),
        "published_on": date(2025, 1, 1),
        "buyer_name": "Stadtwerke Heidelberg GmbH",
        "offers": 4,
    }
    return Tender(**{**base, **values})  # pyright: ignore[reportArgumentType]


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    async with db.session() as session:
        session.add_all(
            [
                Municipality(
                    ags="08221000",
                    name="Heidelberg",
                    population=160_000,
                    latitude=49.41,
                    longitude=8.69,
                ),
                Municipality(
                    ags="08226095",
                    name="Walldorf",
                    population=15_800,
                    latitude=49.31,
                    longitude=8.64,
                ),
                Municipality(
                    ags="09162000",
                    name="München",
                    population=1_500_000,
                    latitude=48.14,
                    longitude=11.58,
                ),
            ]
        )
        session.add(
            PostCode(post_code="69190", locality="Walldorf", municipality_ags="08226095", streets=5)
        )
        await session.flush()
        won = tender("won", "08221000", TenderStatus.AWARDED, awarded_on=date(2024, 6, 1))
        rival = tender("rival", "08221000", TenderStatus.AWARDED, awarded_on=date(2024, 9, 1))
        session.add_all(
            [
                won,
                rival,
                tender(
                    "open",
                    "08221000",
                    TenderStatus.PUBLISHED,
                    deadline_on=date(2026, 4, 1),
                    estimated_value_eur=900_000,
                ),
                tender("far", "09162000", TenderStatus.PUBLISHED, deadline_on=date(2026, 4, 1)),
                tender("closed", "08221000", TenderStatus.PUBLISHED, deadline_on=date(2026, 1, 1)),
            ]
        )
        await session.flush()
        session.add(
            TenderAward(tender_id=won.id, winner_name="Muster Tiefbau GmbH", winner_ags="08226095")
        )
        session.add(
            TenderAward(
                tender_id=rival.id,
                winner_name="Rivale Bau AG",
                winner_ags="09162000",
                winner_size="large",
            )
        )
    yield db
    await db.dispose()


async def contractor_tenant(db: Database) -> Tenant:
    async with db.session() as session:
        return await tenancy.create(
            session,
            name="Muster Tiefbau GmbH",
            slug="muster",
            kind="contractor",
            owner="basic:alice",
            names=["Muster Tiefbau GmbH"],
            site_post_code="69190",
            reach_km=100,
        )


async def test_open_tenders_in_reach_come_first_with_their_chance_and_form(db: Database) -> None:
    tenant = await contractor_tenant(db)
    async with db.session() as session:
        found = await opportunities.opportunities(session, tenant.id, TODAY)

    open_ones = [o for o in found if o.kind == "open"]
    assert [o.title for o in open_ones] == ["Wärmenetz open"]  # München is too far, one is closed
    first = open_ones[0]
    assert first.distance_km == pytest.approx(11, abs=2)
    assert 0 < first.win_chance <= 1
    assert "won_with_buyer" in first.reasons
    assert (first.form.basis, first.expected_offers) == ("buyer", 4.0)


async def test_with_a_model_the_public_record_raises_the_chance(db: Database) -> None:
    tenant = await contractor_tenant(db)
    async with db.session() as session:
        await opportunities.store_win_model(
            session,
            WinModel((-1.0, 1.5, 0.5, 0.2, 0.0)),
            {"tested": 0},
            trained_until=date(2024, 9, 1),
        )
    async with db.session() as session:
        model = await opportunities.win_model(session)
        found = await opportunities.opportunities(session, tenant.id, TODAY)

    assert model is not None
    assert model.coef[1] == 1.5
    (first,) = [o for o in found if o.kind == "open"]
    assert first.win_chance > 0.5


async def test_expected_tenders_follow_the_forecast_within_reach(db: Database) -> None:
    tenant = await contractor_tenant(db)
    async with db.session() as session:
        model = await service.ensure_heuristic(session)
        await service.predict(session, model, await service.load_history(session), TODAY)
    async with db.session() as session:
        found = await opportunities.opportunities(session, tenant.id, TODAY)

    expected = [o for o in found if o.kind == "expected"]
    assert {o.municipality_ags for o in expected} == {"08221000", "08226095"}
    assert all(
        o.tender_chance is None and o.forecast_rank for o in expected
    )  # a heuristic only ranks


async def test_enough_own_bids_calibrate_the_chance(db: Database) -> None:
    tenant = await contractor_tenant(db)
    async with db.session() as session:
        session.add_all(
            Bid(
                tenant_id=tenant.id,
                ref=f"b{i}",
                title="t",
                submitted_on=date(2025, 1, 1),
                outcome=BidOutcome.WON if i < 10 else BidOutcome.LOST,
            )
            for i in range(25)
        )
    async with db.session() as session:
        market = opportunities.Market.of(await opportunities.awards(session))
        firm = await opportunities.contractor(session, tenant.id, market)

    assert (firm.decided, firm.won) == (25, 10)
    assert opportunities.calibrated(0.2, firm, 0.25) == pytest.approx(0.2 * (11 / 27) / 0.25)
    assert opportunities.calibrated(0.2, firm, None) == 0.2
