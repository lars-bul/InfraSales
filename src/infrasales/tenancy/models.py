"""Tenants, their members and subscriptions, and the private zone (ADR 06 §3).

A tenant is a customer as an organisation: a construction company, planner or manufacturer, a
contracting authority, a private builder, a financier, or the platform itself. Users belong to
tenants through memberships. Every private table carries `tenant_id`: the code filters by it, and
on PostgreSQL row-level security returns only the rows of the tenant the transaction is bound to
(`infrasales.tenancy.context`). A private record says what its tenant consented to use it for
(`purposes`): its own model (Modell B), the pools for contracting authorities or financiers.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from infrasales.core.models import SUBJECT_LENGTH, BaseTable, JSONType, UTCDateTime, enum_type
from infrasales.projects.models import AGS_LENGTH, MAX_NAME_LENGTH, POST_CODE_LENGTH, TenderKind


class TenantKind(StrEnum):
    CONTRACTOR = "contractor"  # construction company, planner, manufacturer: product 1
    CONTRACTING_AUTHORITY = "contracting_authority"  # municipality, utility, network operator
    PRIVATE_BUILDER = "private_builder"  # contracting, cooperative, housing, developer, industry
    FINANCIER = "financier"  # bank, development bank, insurer: product 3
    PLATFORM = "platform"  # our team: back office


class MemberRole(StrEnum):
    OWNER = "owner"  # manages the tenant's members and subscription
    MEMBER = "member"
    OPERATOR = "operator"  # platform only: runs the back office
    CURATOR = "curator"  # platform only: reviews claims


class Purpose(StrEnum):
    """What a tenant consented to use a private record for; none: it stays private."""

    OWN_MODEL = "own_model"  # Modell B: the tenant's own predictions
    POOL_AUTHORITIES = "pool_authorities"  # product 2, aggregated (≥ 5 firms, ≥ 12 months)
    POOL_FINANCIERS = "pool_financiers"  # product 3, aggregated


class Tenant(BaseTable, table=True):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    slug: str = Field(max_length=64, unique=True)
    kind: TenantKind = Field(sa_type=enum_type(TenantKind))
    # A contracting authority may stand for a municipality or an actor of the project file.
    municipality_ags: str | None = Field(
        default=None, foreign_key="municipality.ags", max_length=AGS_LENGTH
    )
    actor_id: uuid.UUID | None = Field(default=None, foreign_key="actor.id")


class Membership(BaseTable, table=True):
    __table_args__ = (UniqueConstraint("tenant_id", "subject"),)

    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", ondelete="CASCADE")
    subject: str = Field(max_length=SUBJECT_LENGTH, index=True)  # as sessions know the user
    role: MemberRole = Field(default=MemberRole.MEMBER, sa_type=enum_type(MemberRole))


class Subscription(BaseTable, table=True):
    """What a tenant may see: a product, in regions (AGS prefixes), for a time."""

    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", ondelete="CASCADE", index=True)
    product: str = Field(max_length=64)  # e.g. "heat-network-signals"
    regions: list[str] = Field(default_factory=list[str], sa_type=JSONType)  # [] everywhere
    starts_on: date
    ends_on: date | None = None


# The private zone: every table below has tenant_id and row-level security.


class CompanyProfile(BaseTable, table=True):
    """What a contractor does: the work it bids for, its size, and the names it wins under.

    `names` match the tenant to winners of public awards, so its own history of wins is known
    from the start, before it enters a single bid.
    """

    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", ondelete="CASCADE", unique=True)
    names: list[str] = Field(
        default_factory=list[str], sa_type=JSONType
    )  # legal name, trading names
    kinds: list[TenderKind] = Field(default_factory=list[TenderKind], sa_type=JSONType)
    cpv: list[str] = Field(default_factory=list[str], sa_type=JSONType)  # prefixes, e.g. "452321"
    min_value_eur: int | None = Field(default=None, ge=0)  # contracts it bids for, by value
    max_value_eur: int | None = Field(default=None, ge=0)
    annual_capacity_eur: int | None = Field(default=None, ge=0)
    size: str | None = Field(default=None, max_length=16)  # micro, small, medium, large


class CompanySite(BaseTable, table=True):
    """A place a contractor works from: distance to a site matters for whether it wins."""

    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", ondelete="CASCADE", index=True)
    name: str = Field(max_length=MAX_NAME_LENGTH)
    post_code: str | None = Field(default=None, max_length=POST_CODE_LENGTH)
    municipality_ags: str | None = Field(default=None, max_length=AGS_LENGTH)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    max_distance_km: int | None = Field(default=None, gt=0)  # how far it goes for work


class BidOutcome(StrEnum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"
    WITHDRAWN = "withdrawn"


class Bid(BaseTable, table=True):
    """A bid the tenant made (or makes): the history its own model learns from (Modell B)."""

    __table_args__ = (UniqueConstraint("tenant_id", "ref"),)

    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", ondelete="CASCADE")
    ref: str = Field(max_length=200)  # the tenant's own id: an import can be repeated
    tender_id: uuid.UUID | None = Field(default=None, foreign_key="tender.id", index=True)
    title: str = Field(max_length=500)
    buyer_name: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    municipality_ags: str | None = Field(default=None, max_length=AGS_LENGTH)
    kind: TenderKind = Field(default=TenderKind.CONSTRUCTION, sa_type=enum_type(TenderKind))
    submitted_on: date
    value_eur: int | None = Field(default=None, ge=0)  # the tenant's price
    outcome: BidOutcome = Field(default=BidOutcome.PENDING, sa_type=enum_type(BidOutcome))
    rank: int | None = Field(default=None, ge=1)  # its place among the offers, if told
    offers: int | None = Field(default=None, ge=1)  # how many offers there were, if told
    winning_value_eur: int | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=2000)
    purposes: list[Purpose] = Field(default_factory=list[Purpose], sa_type=JSONType)


class Stage(StrEnum):
    WATCH = "watch"
    QUALIFY = "qualify"
    BID = "bid"
    NO_BID = "no_bid"
    WON = "won"
    LOST = "lost"


class Pursuit(BaseTable, table=True):
    """A tender in the tenant's pipeline, with its bid decision and why."""

    __table_args__ = (UniqueConstraint("tenant_id", "tender_id"),)

    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", ondelete="CASCADE")
    tender_id: uuid.UUID = Field(foreign_key="tender.id", ondelete="CASCADE")
    stage: Stage = Field(default=Stage.WATCH, sa_type=enum_type(Stage))
    reason: str = Field(default="", max_length=2000)
    decided_by: str | None = Field(default=None, max_length=SUBJECT_LENGTH)
    decided_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    purposes: list[Purpose] = Field(default_factory=list[Purpose], sa_type=JSONType)


PRIVATE_TABLES = ("company_profile", "company_site", "bid", "pursuit")
