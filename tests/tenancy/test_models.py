from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy import exc
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.tenancy.models import (
    PRIVATE_TABLES,
    Bid,
    BidOutcome,
    MemberRole,
    Membership,
    Purpose,
    Tenant,
    TenantKind,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


async def a_tenant(db: Database, slug: str = "muster-tiefbau") -> Tenant:
    tenant = Tenant(name="Muster Tiefbau GmbH", slug=slug, kind=TenantKind.CONTRACTOR)
    async with db.session() as session:
        session.add(tenant)
    return tenant


async def test_a_user_belongs_to_a_tenant_once(db: Database) -> None:
    tenant = await a_tenant(db)
    async with db.session() as session:
        session.add(Membership(tenant_id=tenant.id, subject="basic:alice", role=MemberRole.OWNER))

    with pytest.raises(exc.IntegrityError):
        async with db.session() as session:
            session.add(Membership(tenant_id=tenant.id, subject="basic:alice"))


async def test_a_bid_is_private_with_the_purposes_its_tenant_consented_to(db: Database) -> None:
    tenant = await a_tenant(db)
    async with db.session() as session:
        session.add(
            Bid(
                tenant_id=tenant.id,
                ref="A-2025-17",
                title="Fernwärme Bahnstadt",
                submitted_on=date(2025, 5, 2),
                outcome=BidOutcome.LOST,
                purposes=[Purpose.OWN_MODEL],
            )
        )
    async with db.session() as session:
        (bid,) = (await session.exec(select(Bid))).all()

    assert (bid.outcome, bid.purposes) == (BidOutcome.LOST, [Purpose.OWN_MODEL])
    assert "bid" in PRIVATE_TABLES


async def test_deleting_a_tenant_deletes_its_private_rows(db: Database) -> None:
    tenant = await a_tenant(db)
    async with db.session() as session:
        session.add(Bid(tenant_id=tenant.id, ref="1", title="t", submitted_on=date(2025, 1, 1)))
    async with db.session() as session:
        await session.delete(await session.get_one(Tenant, tenant.id))
    async with db.session() as session:
        assert (await session.exec(select(Bid))).all() == []
