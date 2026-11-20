"""Histories for the forecast's tests: hand-made ones, and a synthetic world to learn from."""

import random
from datetime import date

from infrasales.core.db import Database
from infrasales.forecast.features import (
    History,
    MetricFact,
    Place,
    SignalFact,
    TenderFact,
    add_months,
)
from infrasales.projects.models import (
    MetricKind,
    Municipality,
    Signal,
    SignalKind,
    Tender,
    TenderKind,
    TenderOrigin,
    TenderStatus,
)

HEIDELBERG = Place("08221000", "Heidelberg", 162_000, 108.8)
ULM = Place("08421000", "Ulm", 128_000, 118.7)
WALDDORF = Place("08226095", "Walldorf", 15_800, 19.9)
START = date(2017, 1, 1)


def construction(  # noqa: PLR0913  # a tender's fields, keyword-only
    published_on: date,
    *,
    available_on: date | None = None,
    origin: TenderOrigin = TenderOrigin.NOTICE,
    status: TenderStatus = TenderStatus.PUBLISHED,
    kind: TenderKind = TenderKind.CONSTRUCTION,
    framework: bool = False,
    contract_end_on: date | None = None,
) -> TenderFact:
    return TenderFact(
        kind,
        origin,
        status,
        available_on or published_on,
        published_on,
        framework,
        contract_end_on,
    )


def signal(kind: SignalKind, available_on: date, occurred_on: date | None = None) -> SignalFact:
    return SignalFact(kind, available_on, occurred_on)


def metric(kind: MetricKind, available_on: date, value: float) -> MetricFact:
    return MetricFact(kind, available_on, value)


def world(seed: int = 7, places: int = 300, start: date = START) -> History:
    """Municipalities where a council decision and funding precede a construction tender.

    Two in five decide, get funding within about a year, and tender within two years of the
    decision; all now and then publish unrelated job postings, and a few tender unannounced.
    So a model that learns the order of signals ranks well, and one that does not, does not.
    """
    rng = random.Random(seed)  # noqa: S311  # test data, no secret
    all_places = [
        Place(f"08{i:06d}", f"Gemeinde {i}", rng.randint(2_000, 200_000), rng.uniform(5, 200))
        for i in range(places)
    ]
    signals: list[tuple[str, SignalFact]] = []
    tenders: list[tuple[str, TenderFact]] = []
    for place in all_places:
        for _ in range(rng.randint(0, 2)):
            day = add_months(start, rng.randint(0, 95))
            signals.append((place.ags, signal(SignalKind.JOB_POSTING, day)))
        if rng.random() < 0.4:
            decided = add_months(start, rng.randint(0, 84))
            signals.append((place.ags, signal(SignalKind.COUNCIL_DECISION, decided)))
            funded = add_months(decided, rng.randint(6, 14))
            signals.append((place.ags, signal(SignalKind.FUNDING_GRANTED, funded)))
            tendered = add_months(decided, rng.randint(10, 24))
            tenders.append((place.ags, construction(tendered)))
        elif rng.random() < 0.05:  # a tender nothing announced: noise
            tenders.append((place.ags, construction(add_months(start, rng.randint(0, 95)))))
    last = add_months(start, 108)
    signals.append((all_places[0].ags, signal(SignalKind.JOB_POSTING, last)))  # observed until
    return History.of(all_places, signals, tenders)


async def store(db: Database, history: History) -> None:
    """Write `history` to the database, as imports and collectors would."""
    async with db.session() as session:
        session.add_all(
            Municipality(ags=p.ags, name=p.name, population=p.population, area_km2=p.area_km2)
            for p in history.places.values()
        )
        await session.flush()
        session.add_all(
            Signal(
                kind=s.kind,
                municipality_ags=ags,
                available_on=s.available_on,
                occurred_on=s.occurred_on,
                ref=f"test:signal:{ags}:{i}",
            )
            for ags, facts in history.signals.items()
            for i, s in enumerate(facts)
        )
        session.add_all(
            Tender(
                origin=t.origin,
                ref=f"test:tender:{ags}:{i}",
                kind=t.kind,
                status=t.status,
                title=f"Wärmenetz {ags}",
                municipality_ags=ags,
                available_on=t.available_on,
                published_on=t.published_on,
                framework=t.framework,
                contract_end_on=t.contract_end_on,
            )
            for ags, facts in history.tenders.items()
            for i, t in enumerate(facts)
        )
