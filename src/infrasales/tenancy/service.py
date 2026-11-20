"""Tenants and what a request may do in their name.

A signed-in user acts for a tenant they belong to (`membership_of`); every private query then
filters by that tenant and binds the transaction to it (`infrasales.tenancy.context`).
"""

import uuid
from datetime import UTC, datetime

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.projects.models import Municipality, PostCode, TenderKind
from infrasales.tenancy.context import bind
from infrasales.tenancy.models import (
    CompanyProfile,
    CompanySite,
    MemberRole,
    Membership,
    Subscription,
    Tenant,
    TenantKind,
)

PRODUCT = "heat-network-signals"


async def create(  # noqa: PLR0913  # what a tenant starts with
    session: AsyncSession,
    *,
    name: str,
    slug: str,
    kind: str,
    owner: str,
    names: list[str],
    site_post_code: str | None = None,
    reach_km: int | None = None,
) -> Tenant:
    """A tenant with its owner, a subscription everywhere, its profile and (if given) its site."""
    tenant = Tenant(name=name, slug=slug, kind=TenantKind(kind))
    session.add(tenant)
    await session.flush()
    await bind(session, tenant.id)
    session.add(Membership(tenant_id=tenant.id, subject=owner, role=MemberRole.OWNER))
    session.add(
        Subscription(tenant_id=tenant.id, product=PRODUCT, starts_on=datetime.now(UTC).date())
    )
    session.add(CompanyProfile(tenant_id=tenant.id, names=names, kinds=[TenderKind.CONSTRUCTION]))
    if site_post_code:
        session.add(await site(session, tenant.id, name, site_post_code, reach_km))
    await session.flush()
    return tenant


async def site(
    session: AsyncSession, tenant_id: uuid.UUID, name: str, post_code: str, reach_km: int | None
) -> CompanySite:
    """A site at `post_code`, at the centre of the municipality most of its streets lie in."""
    areas = (await session.exec(select(PostCode).where(col(PostCode.post_code) == post_code))).all()
    ags = max(areas, key=lambda a: a.streets).municipality_ags if areas else None
    place = (await session.exec(select(Municipality).where(col(Municipality.ags) == ags))).first()
    return CompanySite(
        tenant_id=tenant_id,
        name=name,
        post_code=post_code,
        municipality_ags=ags,
        latitude=place.latitude if place else None,
        longitude=place.longitude if place else None,
        max_distance_km=reach_km,
    )


async def membership_of(
    session: AsyncSession, subject: str, tenant_id: uuid.UUID | None = None
) -> Membership | None:
    """The user's membership: of the tenant asked for, else their first."""
    statement = select(Membership).where(col(Membership.subject) == subject)
    if tenant_id is not None:
        statement = statement.where(col(Membership.tenant_id) == tenant_id)
    membership = (await session.exec(statement.order_by(col(Membership.created_at)))).first()
    if membership is not None:
        await bind(session, membership.tenant_id)
    return membership
