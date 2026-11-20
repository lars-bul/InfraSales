from datetime import date

import httpx2
import pytest
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.projects.models import (
    Municipality,
    PostCode,
    Tender,
    TenderKind,
    TenderOrigin,
    TenderStatus,
)
from infrasales.tenancy import service
from infrasales.tenancy.models import Bid, BidOutcome, Purpose
from tests.helpers import SAME_ORIGIN, sign_in

pytestmark = pytest.mark.anyio


async def a_company(database_url: str) -> None:
    db = Database(database_url)
    async with db.session() as session:
        session.add(Municipality(ags="08221000", name="Heidelberg", latitude=49.41, longitude=8.69))
        session.add(
            PostCode(
                post_code="69117", locality="Heidelberg", municipality_ags="08221000", streets=4
            )
        )
        await session.flush()
        session.add(
            Tender(
                origin=TenderOrigin.NOTICE,
                ref="proc:x:LOT-0000",
                kind=TenderKind.CONSTRUCTION,
                status=TenderStatus.PUBLISHED,
                title="Fernwärme Bahnstadt",
                municipality_ags="08221000",
                available_on=date(2026, 1, 1),
                published_on=date.today(),  # noqa: DTZ011  # open now, whenever the test runs
            )
        )
        await service.create(
            session,
            name="Muster Tiefbau GmbH",
            slug="muster",
            kind="contractor",
            owner="basic:alice",
            names=["Muster Tiefbau GmbH"],
            site_post_code="69117",
            reach_km=50,
        )
    await db.dispose()


async def test_a_user_without_a_company_has_no_customer_area(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "vera")

    response = await client.get("/api/company/opportunities")

    assert response.status_code == 403


async def test_a_member_sees_the_companys_chances(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await a_company(database_url)
    await sign_in(client, "alice")

    found = (await client.get("/api/company/opportunities")).json()

    (first,) = [o for o in found if o["kind"] == "open"]
    assert first["title"] == "Fernwärme Bahnstadt"
    assert first["distance_km"] == 0.0
    assert 0 < first["win_chance"] <= 1
    assert first["form"]["basis"] == "all"


async def test_the_profile_and_sites_are_the_companys_to_change(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await a_company(database_url)
    await sign_in(client, "alice")

    changed = await client.put(
        "/api/company",
        json={
            "names": ["Muster Tiefbau GmbH", "Muster Bau"],
            "kinds": ["construction", "planning"],
            "max_value_eur": 5_000_000,
        },
        headers=SAME_ORIGIN,
    )
    added = await client.post(
        "/api/company/sites",
        json={"name": "Lager Süd", "post_code": "69117", "max_distance_km": 80},
        headers=SAME_ORIGIN,
    )
    removed = await client.delete(f"/api/company/sites/{added.json()['id']}", headers=SAME_ORIGIN)
    missing = await client.delete(f"/api/company/sites/{added.json()['id']}", headers=SAME_ORIGIN)
    profile = (await client.get("/api/company")).json()

    assert changed.json()["names"] == ["Muster Tiefbau GmbH", "Muster Bau"]
    assert added.json()["municipality_ags"] == "08221000"
    assert (removed.status_code, missing.status_code) == (204, 404)
    assert [site["name"] for site in profile["sites"]] == ["Muster Tiefbau GmbH"]
    assert profile["max_value_eur"] == 5_000_000


async def test_own_bids_import_all_or_nothing(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await a_company(database_url)
    await sign_in(client, "alice")
    headers = SAME_ORIGIN | {"content-type": "text/csv"}
    good = (
        "ref,title,submitted_on,outcome,value_eur\n"
        "A-1,Fernwärme Süd,2025-03-01,won,410000\n"
        "A-2,Nahwärme,2025-05-01,lost,\n"
    )

    first = await client.post("/api/company/bids", content=good, headers=headers)
    again = await client.post("/api/company/bids", content=good, headers=headers)
    bad = await client.post(
        "/api/company/bids",
        content="ref,title,submitted_on,outcome\nA-3,x,gestern,won\n",
        headers=headers,
    )
    columns = await client.post("/api/company/bids", content="ref,title\nA-4,x\n", headers=headers)

    assert (first.json()["new"], again.json()["updated"]) == (2, 2)
    assert bad.json()["errors"][0].startswith("line 2:")
    assert columns.status_code == 422
    db = Database(database_url)
    async with db.session() as session:
        bids = (await session.exec(select(Bid).order_by(Bid.ref))).all()
    await db.dispose()
    assert [(b.ref, b.outcome, b.value_eur, b.purposes) for b in bids] == [
        ("A-1", BidOutcome.WON, 410000, [Purpose.OWN_MODEL]),
        ("A-2", BidOutcome.LOST, None, [Purpose.OWN_MODEL]),
    ]
