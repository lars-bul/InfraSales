"""The customer area: a contractor's chances, its profile and sites, its own bids (ADR 06 §12).

Every route acts for the tenant the signed-in user belongs to; a user without a membership has
no customer area. Private rows are always filtered by that tenant, and on PostgreSQL the
transaction is bound to it (row-level security).
"""

import csv
import io
import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import col, select

from infrasales.auth.deps import CurrentUser
from infrasales.core.db import Session
from infrasales.forecast import opportunities as chances
from infrasales.projects.models import TenderKind
from infrasales.tenancy import service
from infrasales.tenancy.models import (
    Bid,
    BidOutcome,
    CompanyProfile,
    CompanySite,
    Membership,
    Purpose,
)

router = APIRouter(prefix="/api/company", tags=["company"])


async def _membership(user: CurrentUser, session: Session) -> Membership:
    membership = await service.membership_of(session, user.subject)
    if membership is None:
        raise HTTPException(403, "No company: ask your company's owner for an invitation")
    return membership


Member = Annotated[Membership, Depends(_membership)]


class FormRead(BaseModel):
    basis: str
    tenders: int
    procedure: str | None
    procedure_share: float | None
    lots_median: float | None
    framework_share: float
    price_only_share: float | None
    duration_months_median: float | None
    value_eur_median: int | None
    offers_median: float | None


class OpportunityRead(BaseModel):
    kind: str  # "open" or "expected"
    tender_id: uuid.UUID | None
    title: str
    municipality_ags: str | None
    municipality: str | None
    buyer: str | None
    distance_km: float | None
    win_chance: float
    tender_chance: float | None
    forecast_rank: int | None
    deadline_on: date | None
    value_eur: int | None
    expected_offers: float | None
    form: FormRead
    reasons: list[str]


@router.get("/opportunities")
async def list_opportunities(
    member: Member, session: Session, limit: Annotated[int, Field(ge=1, le=200)] = 50
) -> list[OpportunityRead]:
    """The company's best chances: open tenders in reach, then municipalities expected to tender."""
    today = datetime.now(UTC).date()
    found = await chances.opportunities(session, member.tenant_id, today, limit=limit)
    return [
        OpportunityRead.model_validate(
            {**{name: getattr(o, name) for name in o.__slots__}, "form": o.form.as_json()}
        )
        for o in found
    ]


class SiteRead(BaseModel):
    id: uuid.UUID
    name: str
    post_code: str | None
    municipality_ags: str | None
    max_distance_km: int | None


class ProfileRead(BaseModel):
    names: list[str]
    kinds: list[TenderKind]
    min_value_eur: int | None
    max_value_eur: int | None
    sites: list[SiteRead]


class ProfileUpdate(BaseModel):
    names: list[str] = Field(min_length=1, max_length=20)
    kinds: list[TenderKind] = Field(min_length=1)
    min_value_eur: int | None = Field(default=None, ge=0)
    max_value_eur: int | None = Field(default=None, ge=0)


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    post_code: str = Field(pattern=r"^\d{5}$")
    max_distance_km: int | None = Field(default=None, gt=0, le=1000)


async def _profile(session: Session, tenant_id: uuid.UUID) -> ProfileRead:
    profile = (
        await session.exec(select(CompanyProfile).where(col(CompanyProfile.tenant_id) == tenant_id))
    ).first()
    sites = (
        await session.exec(select(CompanySite).where(col(CompanySite.tenant_id) == tenant_id))
    ).all()
    return ProfileRead(
        names=profile.names if profile else [],
        kinds=profile.kinds if profile else [],
        min_value_eur=profile.min_value_eur if profile else None,
        max_value_eur=profile.max_value_eur if profile else None,
        sites=[SiteRead.model_validate(site, from_attributes=True) for site in sites],
    )


@router.get("")
async def read_profile(member: Member, session: Session) -> ProfileRead:
    """The company's profile: the names it wins under, the work it does, its sites."""
    return await _profile(session, member.tenant_id)


@router.put("")
async def update_profile(change: ProfileUpdate, member: Member, session: Session) -> ProfileRead:
    profile = (
        await session.exec(
            select(CompanyProfile).where(col(CompanyProfile.tenant_id) == member.tenant_id)
        )
    ).first() or CompanyProfile(tenant_id=member.tenant_id)
    profile.names = change.names
    profile.kinds = change.kinds
    profile.min_value_eur = change.min_value_eur
    profile.max_value_eur = change.max_value_eur
    session.add(profile)
    await session.flush()
    return await _profile(session, member.tenant_id)


@router.post("/sites", status_code=201)
async def add_site(new: SiteCreate, member: Member, session: Session) -> SiteRead:
    site = await service.site(
        session, member.tenant_id, new.name, new.post_code, new.max_distance_km
    )
    session.add(site)
    await session.flush()
    return SiteRead.model_validate(site, from_attributes=True)


@router.delete(
    "/sites/{site_id}", status_code=204, responses={404: {"description": "No such site"}}
)
async def delete_site(site_id: uuid.UUID, member: Member, session: Session) -> None:
    site = (
        await session.exec(
            select(CompanySite).where(
                col(CompanySite.id) == site_id, col(CompanySite.tenant_id) == member.tenant_id
            )
        )
    ).first()
    if site is None:
        raise HTTPException(404, "No such site")
    await session.delete(site)


class BidsImported(BaseModel):
    new: int
    updated: int
    errors: list[str]


BID_FIELDS = {"ref", "title", "submitted_on", "outcome"}


@router.post("/bids", responses={422: {"description": "A row could not be read"}})
async def import_bids(
    member: Member,
    session: Session,
    text: Annotated[
        str, Body(media_type="text/csv", description="ref,title,submitted_on,outcome,…")
    ],
    own_model: bool = True,  # noqa: FBT001, FBT002  # a query flag: consent for Modell B
) -> BidsImported:
    """Import the company's own bids as CSV: all of them, or none and the errors why.

    Columns: ref, title, submitted_on, outcome (won, lost, pending, withdrawn), and if known
    buyer_name, value_eur, rank, offers, winning_value_eur. With `own_model`, they calibrate the
    company's own chances (Modell B).
    """
    rows = list(csv.DictReader(io.StringIO(text.removeprefix("\ufeff"))))
    missing = BID_FIELDS - set(rows[0] if rows else {})
    if missing:
        raise HTTPException(422, f"Missing columns: {', '.join(sorted(missing))}")
    stored = {
        b.ref: b
        for b in await session.exec(select(Bid).where(col(Bid.tenant_id) == member.tenant_id))
    }
    result = BidsImported(new=0, updated=0, errors=[])
    for line, row in enumerate(rows, start=2):
        try:
            bid = stored.get(row["ref"]) or Bid(
                tenant_id=member.tenant_id, ref=row["ref"], title="", submitted_on=date.min
            )
            bid.title = row["title"][:500]
            bid.submitted_on = date.fromisoformat(row["submitted_on"])
            bid.outcome = BidOutcome(row["outcome"].strip().lower())
            bid.buyer_name = row.get("buyer_name") or None
            bid.value_eur = _number(row.get("value_eur"))
            bid.rank = _number(row.get("rank"))
            bid.offers = _number(row.get("offers"))
            bid.winning_value_eur = _number(row.get("winning_value_eur"))
            bid.purposes = [Purpose.OWN_MODEL] if own_model else []
        except (KeyError, ValueError) as error:
            result.errors.append(f"line {line}: {error}")
            continue
        result.updated += row["ref"] in stored
        result.new += row["ref"] not in stored
        session.add(bid)
    if result.errors:
        await session.rollback()
        return BidsImported(new=0, updated=0, errors=result.errors[:50])
    return result


def _number(text: str | None) -> int | None:
    return int(float(text)) if text and text.strip() else None
