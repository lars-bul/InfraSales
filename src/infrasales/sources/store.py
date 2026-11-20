"""Lots from every source merged into the tenders, one per procedure and lot, with their awards.

A procedure's notices (prior information, contract notice, award) share its eForms id, in TED and
in the Datenservice alike, so a lot is one tender however many notices and sources tell of it. A
later notice moves its status on (planned → published → awarded or cancelled) and fills in what it
knows; the earliest notice sets when the public could first know (`available_on`). Older notices
without a procedure id are a tender each. Only lots that concern a heat network are kept; the
others stay in the raw exports, to be read again when the rules change.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.projects.models import (
    Municipality,
    PostCode,
    Tender,
    TenderAward,
    TenderOrigin,
    TenderStatus,
)
from infrasales.sources.places import PostCodeArea, Resolver
from infrasales.sources.records import LotRecord

CHUNK = 500
RANK = {
    TenderStatus.PLANNED: 0,
    TenderStatus.PUBLISHED: 1,
    TenderStatus.CANCELLED: 2,
    TenderStatus.AWARDED: 2,
}
# What a later notice may fill in or correct.
FIELDS = (
    "buyer_name", "buyer_post_code", "buyer_city", "place_post_code", "place_city", "place_nuts",
    "procedure", "lots", "duration_months", "price_only", "sme_suitable", "deadline_on",
    "awarded_on", "contract_end_on", "estimated_value_eur", "award_value_eur", "lowest_offer_eur",
    "highest_offer_eur", "offers", "url",
)  # fmt: skip


@dataclass(slots=True)
class Stored:
    tenders_new: int = 0
    tenders_updated: int = 0
    awards_new: int = 0
    skipped: int = 0  # not a heat network


async def resolver(session: AsyncSession) -> Resolver:
    """A resolver from the stored municipalities and post codes."""
    municipalities = (await session.exec(select(Municipality.ags, Municipality.name))).all()
    areas = (await session.exec(select(PostCode))).all()
    return Resolver.of(
        municipalities,
        (PostCodeArea(a.post_code, a.locality, a.municipality_ags, a.streets) for a in areas),
    )


async def store(session: AsyncSession, lots: Iterable[LotRecord], places: Resolver) -> Stored:
    """Merge `lots` into the tenders and their awards."""
    result = Stored()
    wanted: dict[str, list[LotRecord]] = {}
    for lot in sorted(lots, key=lambda lot: (lot.published_on, lot.notice_id)):
        if not (lot.relevance.heat_network or _pipeline_award(lot)):
            result.skipped += 1
            continue
        wanted.setdefault(lot.key, []).append(lot)
    existing = await _existing(session, list(wanted))
    known = set(places.names)
    for key, records in wanted.items():
        tender = existing.get(key)
        if tender is None:
            tender = _new(key, records[0])
            result.tenders_new += 1
        else:
            result.tenders_updated += 1
        for record in records:
            _merge(tender, record)
        ags = (
            places.resolve(tender.place_post_code, tender.place_city, tender.place_nuts)
            or places.resolve(tender.buyer_post_code, tender.buyer_city, tender.place_nuts)
            or places.resolve_buyer(tender.buyer_name, tender.place_nuts)
        )
        tender.municipality_ags = ags if ags in known else None
        session.add(tender)
        await session.flush()
        result.awards_new += await _awards(session, tender, records, places)
    return result


async def _existing(session: AsyncSession, keys: Sequence[str]) -> dict[str, Tender]:
    found: dict[str, Tender] = {}
    for start in range(0, len(keys), CHUNK):
        chunk = keys[start : start + CHUNK]
        statement = select(Tender).where(
            col(Tender.origin) == TenderOrigin.NOTICE, col(Tender.ref).in_(chunk)
        )
        found.update({tender.ref: tender for tender in await session.exec(statement)})
    return found


def _pipeline_award(lot: LotRecord) -> bool:
    """A pipeline work of another medium that names its winner: kept for the market, not shown."""
    return lot.relevance.reason == "pipeline" and bool(lot.awards)


def _new(key: str, record: LotRecord) -> Tender:
    return Tender(
        origin=TenderOrigin.NOTICE,
        ref=key,
        kind=record.kind,
        status=record.status,
        title=record.title,
        available_on=record.published_on,
        source=record.source,
        procedure_ref=record.procedure_ref,
        notice_type=record.notice_type,
        lot=record.lot,
        cpv=list(record.cpv),
        relevance=record.relevance.reason,
        heat_network=record.relevance.heat_network,
    )


def _merge(tender: Tender, record: LotRecord) -> None:
    tender.available_on = min(tender.available_on, record.published_on)
    if record.status is TenderStatus.PUBLISHED or (
        record.status in {TenderStatus.AWARDED, TenderStatus.CANCELLED}
        and tender.published_on is None
    ):
        # A lot known only from its award: put out to tender no later than the award was told.
        tender.published_on = min(filter(None, [tender.published_on, record.published_on]))
    if RANK[record.status] >= RANK[tender.status]:
        tender.status = record.status
        tender.notice_type = record.notice_type
    if record.source not in tender.source.split("+"):
        tender.source = f"{tender.source}+{record.source}"
    if (
        record.status is TenderStatus.PUBLISHED
        or not tender.title
        or tender.title == record.notice_id
    ):
        tender.title = record.title
        tender.kind = record.kind
    tender.framework = tender.framework or record.framework
    tender.cpv = list(dict.fromkeys([*tender.cpv, *record.cpv]))
    if record.relevance.heat_network and not tender.heat_network:  # one notice says so: it is
        tender.heat_network = True
        tender.relevance = record.relevance.reason
    for name in FIELDS:
        value = getattr(record, name)
        if value is not None:
            setattr(tender, name, value)


async def _awards(
    session: AsyncSession, tender: Tender, records: Sequence[LotRecord], places: Resolver
) -> int:
    seen = {
        award.winner_name
        for award in await session.exec(
            select(TenderAward).where(col(TenderAward.tender_id) == tender.id)
        )
    }
    added = 0
    for record in records:
        for award in record.awards:
            if award.winner_name in seen:
                continue
            seen.add(award.winner_name)
            german = award.country in {None, "DEU", "DE"}
            session.add(
                TenderAward(
                    tender_id=tender.id,
                    winner_name=award.winner_name[:300],
                    winner_identifier=(award.winner_identifier or "")[:100] or None,
                    winner_post_code=award.post_code,
                    winner_city=award.city,
                    winner_country=award.country,
                    winner_size=award.size,
                    winner_ags=places.resolve(award.post_code, award.city) if german else None,
                    value_eur=award.value_eur,
                )
            )
            added += 1
    return added
