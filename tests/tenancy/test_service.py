from collections.abc import AsyncIterator

import pytest
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.projects.models import Municipality, PostCode
from infrasales.tenancy import service
from infrasales.tenancy.models import CompanyProfile, CompanySite, MemberRole, Subscription

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    async with db.session() as session:
        session.add(Municipality(ags="08221000", name="Heidelberg", latitude=49.4, longitude=8.69))
        session.add(
            PostCode(
                post_code="69117", locality="Heidelberg", municipality_ags="08221000", streets=3
            )
        )
    yield db
    await db.dispose()


async def test_a_tenant_starts_with_its_owner_subscription_profile_and_site(db: Database) -> None:
    async with db.session() as session:
        tenant = await service.create(
            session,
            name="Muster Tiefbau GmbH",
            slug="muster-tiefbau",
            kind="contractor",
            owner="basic:alice",
            names=["Muster Tiefbau GmbH"],
            site_post_code="69117",
            reach_km=80,
        )
    async with db.session() as session:
        membership = await service.membership_of(session, "basic:alice")
        profile = (await session.exec(select(CompanyProfile))).one()
        site = (await session.exec(select(CompanySite))).one()
        subscription = (await session.exec(select(Subscription))).one()

    assert membership is not None
    assert (membership.tenant_id, membership.role) == (tenant.id, MemberRole.OWNER)
    assert profile.names == ["Muster Tiefbau GmbH"]
    assert (site.municipality_ags, site.latitude, site.max_distance_km) == ("08221000", 49.4, 80)
    assert (subscription.product, subscription.regions) == ("heat-network-signals", [])


async def test_a_user_without_membership_acts_for_no_tenant(db: Database) -> None:
    async with db.session() as session:
        assert await service.membership_of(session, "basic:vera") is None


async def test_a_site_at_an_unknown_post_code_has_no_place(db: Database) -> None:
    async with db.session() as session:
        tenant = await service.create(
            session, name="X", slug="x", kind="contractor", owner="basic:alice", names=["X"]
        )
        site = await service.site(session, tenant.id, "Lager", "99999", None)

    assert (site.municipality_ags, site.latitude) == (None, None)
