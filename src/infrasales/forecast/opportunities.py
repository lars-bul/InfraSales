"""Where a contractor has the best chance to win: open tenders and expected ones, ranked.

For each open heat network tender within the contractor's reach, and each municipality the forecast
expects to tender soon, it combines:

- the chance the contractor wins if it bids (`infrasales.forecast.winners`), from where it sits,
  what it won under its names in public awards, and its own bids;
- the likely form of the award and the competition (`infrasales.forecast.market`);
- for an expected tender, how likely the municipality tenders at all (Modell A), when the model is
  calibrated; a heuristic's score only ranks.

The tenant's own bids calibrate its chance (Modell B on Modell A): with enough decided bids, the
share it won scales the public model's chance for it.
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import aliased
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.forecast import service as forecast
from infrasales.forecast.firms import firm_key
from infrasales.forecast.market import FormProfile, PastTender, profile
from infrasales.forecast.models import ForecastModel, ModelKind
from infrasales.forecast.winners import Award, Firm, Market, WinModel, chance, distance_km
from infrasales.projects.models import (
    Municipality,
    Tender,
    TenderAward,
    TenderKind,
    TenderStatus,
)
from infrasales.sources.places import normalized
from infrasales.tenancy.models import Bid, BidOutcome, CompanyProfile, CompanySite

WIN_MODEL_NAME = "heat-network-winner"
OPEN_DAYS = 90  # a published tender without a deadline counts as open this long
MIN_DECIDED_BIDS = 20  # fewer, and the tenant's own record does not calibrate its chance
DEFAULT_REACH_KM = 150

type Place = tuple[float, float]


def _place(latitude: float | None, longitude: float | None) -> Place | None:
    return (latitude, longitude) if latitude is not None and longitude is not None else None


async def awards(session: AsyncSession, kind: TenderKind = TenderKind.CONSTRUCTION) -> list[Award]:
    """Every public award of a heat network contract of `kind`.

    With where the work is and where the winner sits.
    """
    work = aliased(Municipality)
    seat = aliased(Municipality)
    statement = (
        select(TenderAward, Tender, work, seat)
        .join(Tender, col(Tender.id) == col(TenderAward.tender_id))
        .join(work, col(work.ags) == col(Tender.municipality_ags))
        .outerjoin(seat, col(seat.ags) == col(TenderAward.winner_ags))
        .where(
            or_(col(Tender.heat_network), col(Tender.relevance) == "pipeline"),
            col(Tender.kind) == kind,
        )
    )
    result: list[Award] = []
    for award, tender, place, firm_seat in await session.exec(statement):
        day = tender.awarded_on or tender.published_on or tender.available_on
        result.append(
            Award(
                tender=str(tender.id),
                day=day,
                buyer=normalized(tender.buyer_name or ""),
                land=place.ags[:2],
                place=_place(place.latitude, place.longitude),
                firm=firm_key(award.winner_name),
                firm_place=_place(firm_seat.latitude, firm_seat.longitude) if firm_seat else None,
                large=award.winner_size == "large",
                heat=tender.heat_network,
            )
        )
    return result


async def past_tenders(
    session: AsyncSession, kind: TenderKind = TenderKind.CONSTRUCTION
) -> list[PastTender]:
    """The heat network tenders of `kind` that came out: the form and competition they had."""
    statement = select(Tender).where(
        col(Tender.heat_network),
        col(Tender.kind) == kind,
        col(Tender.status).in_([TenderStatus.PUBLISHED, TenderStatus.AWARDED]),
    )
    return [
        PastTender(
            buyer=normalized(t.buyer_name or ""),
            ags=t.municipality_ags,
            procedure=t.procedure,
            lots=t.lots,
            framework=t.framework,
            price_only=t.price_only,
            duration_months=t.duration_months,
            value_eur=t.award_value_eur or t.estimated_value_eur,
            offers=t.offers,
            sme_suitable=t.sme_suitable,
        )
        for t in await session.exec(statement)
    ]


@dataclass(slots=True)
class Contractor:
    """A tenant as a firm in the market: its sites, names, the work it does, its record."""

    names: set[str]  # firm keys
    sites: list[tuple[Place, int]]  # place, reach in km
    kinds: set[TenderKind]
    min_value: int | None
    max_value: int | None
    large: bool
    decided: int = 0  # its bids won or lost
    won: int = 0
    wins: list[Award] = field(default_factory=list[Award])

    def nearest(self, place: Place | None) -> tuple[Place | None, float, int]:
        """Its site nearest to `place`: the site, the distance and the site's reach."""
        if not self.sites or place is None:
            return None, math.inf, DEFAULT_REACH_KM
        site, reach = min(self.sites, key=lambda s: distance_km(s[0], place))
        return site, distance_km(site, place), reach


async def contractor(session: AsyncSession, tenant_id: uuid.UUID, market: Market) -> Contractor:
    """The tenant's profile, sites and record: public wins under its names, and its own bids."""
    company = (
        await session.exec(select(CompanyProfile).where(col(CompanyProfile.tenant_id) == tenant_id))
    ).first()
    sites = (
        await session.exec(select(CompanySite).where(col(CompanySite.tenant_id) == tenant_id))
    ).all()
    bids = (await session.exec(select(Bid).where(col(Bid.tenant_id) == tenant_id))).all()
    names = {firm_key(name) for name in (company.names if company else [])}
    result = Contractor(
        names=names,
        sites=[
            (place, site.max_distance_km or DEFAULT_REACH_KM)
            for site in sites
            if (place := _place(site.latitude, site.longitude)) is not None
        ],
        kinds=set(company.kinds) if company and company.kinds else {TenderKind.CONSTRUCTION},
        min_value=company.min_value_eur if company else None,
        max_value=company.max_value_eur if company else None,
        large=(company.size == "large") if company else False,
        decided=sum(1 for b in bids if b.outcome in {BidOutcome.WON, BidOutcome.LOST}),
        won=sum(1 for b in bids if b.outcome is BidOutcome.WON),
    )
    result.wins = [award for award in market.awards if award.firm in names]
    return result


def _typical(form: FormProfile) -> float | None:
    """A typical bidder's chance: one in the usual number of offers."""
    return 1 / form.offers_median if form.offers_median else None


def calibrated(public_chance: float, firm: Contractor, mean_public: float | None) -> float:
    """The public model's chance, scaled by the tenant's own record once it has enough bids.

    Its own share of bids won, against a typical bidder's chance (`mean_public`), says how much
    better or worse it does than the public record alone tells.
    """
    if firm.decided < MIN_DECIDED_BIDS or not mean_public:
        return public_chance
    own_rate = (firm.won + 1) / (firm.decided + 2)  # Laplace: neither 0 nor 1 from few bids
    return min(0.95, public_chance * own_rate / mean_public)


@dataclass(frozen=True, slots=True)
class Opportunity:
    kind: str  # "open": a published tender; "expected": a municipality the forecast expects
    tender_id: uuid.UUID | None
    title: str
    municipality_ags: str | None
    municipality: str | None
    buyer: str | None
    distance_km: float | None
    win_chance: float  # if it bids
    tender_chance: float | None  # expected only, when the forecast is calibrated
    forecast_rank: int | None  # expected only
    deadline_on: date | None
    value_eur: int | None
    expected_offers: float | None
    form: FormProfile
    reasons: list[str]  # what drives its chance, in words for the screen to translate


async def win_model(session: AsyncSession) -> WinModel | None:
    stored = (
        await session.exec(
            select(ForecastModel).where(
                col(ForecastModel.name) == WIN_MODEL_NAME, col(ForecastModel.active)
            )
        )
    ).first()
    if stored is None:
        return None
    return WinModel.from_parameters(
        {k: float(v) for k, v in stored.parameters.items() if isinstance(v, (int, float))}
    )


async def store_win_model(
    session: AsyncSession, model: WinModel, metrics: dict[str, object], *, trained_until: date
) -> ForecastModel:
    """Store a fitted win model and make it the one that serves."""
    stored = ForecastModel(
        name=WIN_MODEL_NAME,
        version=f"choice-{trained_until.isoformat()}-{uuid.uuid4().hex[:6]}",
        kind=ModelKind.CHOICE,
        horizon_months=1,
        features=list(model.features),
        parameters=dict(model.parameters()),
        metrics=metrics,  # pyright: ignore[reportArgumentType]
        trained_until=trained_until,
    )
    session.add(stored)
    await session.flush()
    await forecast.activate(session, stored)
    return stored


def _reasons(firm: Contractor, distance: float, buyer: str, land: str) -> list[str]:
    reasons: list[str] = []
    if distance <= 50:  # noqa: PLR2004
        reasons.append("near")
    if any(w.buyer == buyer for w in firm.wins):
        reasons.append("won_with_buyer")
    if any(w.land == land for w in firm.wins):
        reasons.append("won_in_land")
    if not firm.wins:
        reasons.append("no_public_wins")
    return reasons


async def opportunities(
    session: AsyncSession, tenant_id: uuid.UUID, today: date, *, limit: int = 50
) -> list[Opportunity]:
    """The tenant's best chances: open tenders in reach, then municipalities expected to tender."""
    model = await win_model(session)
    market = Market.of(await awards(session))
    firm = await contractor(session, tenant_id, market)
    past = await past_tenders(session)
    me = Firm(next(iter(firm.names), f"tenant:{tenant_id}"), None, firm.large, firm.wins)
    places = {
        m.ags: m
        for m in await session.exec(
            select(Municipality).where(col(Municipality.latitude).is_not(None))
        )
    }
    found: list[Opportunity] = []
    open_statement = select(Tender).where(
        col(Tender.heat_network),
        col(Tender.status) == TenderStatus.PUBLISHED,
        col(Tender.kind).in_(list(firm.kinds)),
        col(Tender.municipality_ags).is_not(None),
    )
    for tender in await session.exec(open_statement):
        due = tender.deadline_on or (
            (tender.published_on or tender.available_on) + timedelta(days=OPEN_DAYS)
        )
        place_row = places.get(tender.municipality_ags or "")
        if due < today or place_row is None:
            continue
        value = tender.estimated_value_eur
        if value and (
            (firm.min_value and value < firm.min_value)
            or (firm.max_value and value > firm.max_value)
        ):
            continue
        place = _place(place_row.latitude, place_row.longitude)
        site, distance, reach = firm.nearest(place)
        if site is not None and distance > reach:
            continue
        buyer = normalized(tender.buyer_name or "")
        win = _win(
            model,
            market,
            me,
            site=site,
            buyer=buyer,
            land=place_row.ags[:2],
            place=place,
            today=today,
        )
        form = profile(past, buyer=buyer, ags=tender.municipality_ags)
        found.append(
            Opportunity(
                kind="open",
                tender_id=tender.id,
                title=tender.title,
                municipality_ags=tender.municipality_ags,
                municipality=place_row.name,
                buyer=tender.buyer_name,
                distance_km=round(distance, 1) if math.isfinite(distance) else None,
                win_chance=calibrated(win, firm, _typical(form)),
                tender_chance=None,
                forecast_rank=None,
                deadline_on=tender.deadline_on,
                value_eur=value,
                expected_offers=form.offers_median,
                form=form,
                reasons=_reasons(firm, distance, buyer, place_row.ags[:2]),
            )
        )
    found.extend(
        await _expected(
            session,
            firm=firm,
            model=model,
            market=market,
            me=me,
            places=places,
            past=past,
            today=today,
        )
    )
    found.sort(key=lambda o: (o.kind != "open", -o.win_chance * (o.tender_chance or 1.0)))
    return found[:limit]


def _win(  # noqa: PLR0913  # the model, the market and the tender's parties
    model: WinModel | None,
    market: Market,
    me: Firm,
    *,
    site: Place | None,
    buyer: str,
    land: str,
    place: Place | None,
    today: date,
) -> float:
    contractor_here = Firm(me.name, site, me.large, me.wins)
    if model is None:  # no model fitted yet: every firm of the market alike
        firms = len(market.firms(today)) + 1
        return 1 / firms
    return chance(model, market, contractor_here, buyer=buyer, land=land, place=place, day=today)


async def _expected(  # noqa: PLR0913  # what the expected tenders are weighed with
    session: AsyncSession,
    *,
    firm: Contractor,
    model: WinModel | None,
    market: Market,
    me: Firm,
    places: dict[str, Municipality],
    past: Sequence[PastTender],
    today: date,
) -> list[Opportunity]:
    """The municipalities the forecast ranks highest, within the contractor's reach."""
    forecast_model = await forecast.active_model(session)
    as_of = await forecast.latest_day(session, forecast_model) if forecast_model else None
    if forecast_model is None or as_of is None:
        return []
    _, ranked = await forecast.ranking(session, forecast_model, as_of, limit=500)
    calibrated_forecast = forecast_model.kind is ModelKind.LOGISTIC
    by_land: defaultdict[str, int] = defaultdict(int)
    result: list[Opportunity] = []
    for entry in ranked:
        row = places.get(entry.municipality.ags)
        if row is None:
            continue
        place = _place(row.latitude, row.longitude)
        site, distance, reach = firm.nearest(place)
        if site is not None and distance > reach:
            continue
        by_land[row.ags[:2]] += 1
        form = profile(past, buyer=None, ags=row.ags)
        win = _win(
            model, market, me, site=site, buyer="", land=row.ags[:2], place=place, today=today
        )
        result.append(
            Opportunity(
                kind="expected",
                tender_id=None,
                title=row.name,
                municipality_ags=row.ags,
                municipality=row.name,
                buyer=None,
                distance_km=round(distance, 1) if math.isfinite(distance) else None,
                win_chance=calibrated(win, firm, _typical(form)),
                tender_chance=entry.prediction.score if calibrated_forecast else None,
                forecast_rank=entry.rank,
                deadline_on=None,
                value_eur=form.value_eur_median,
                expected_offers=form.offers_median,
                form=form,
                reasons=_reasons(firm, distance, "", row.ags[:2]),
            )
        )
    return result
