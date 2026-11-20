"""What a forecast knows about a municipality on a day: its features, from public data only.

Point in time: a feature uses only what was available by the day (`available_on`), so the features
of a past day are what a forecast on that day could have seen, and a backtest never learns from
the future. Modell A of ADR 06 §4: the demand side only (what a municipality and its utility plan,
decide and put out to tender), never what a construction company bids, earns or has free.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from infrasales.projects.models import (
    MetricKind,
    SignalKind,
    TenderKind,
    TenderOrigin,
    TenderStatus,
)

HORIZON_MONTHS = 24  # a label's: time to get known to the utility and plan for capacity
RECENT_MONTHS = 24  # a signal or tender counts as recent for this long
SOON_MONTHS = 24  # a framework ending within this long may be put out to tender again
CONCESSION_MONTHS = 36
LARGE_CITY = 100_000  # Wärmeplanungsgesetz: heat plans due by 30 June 2026 above, 2028 below
DEADLINE_LARGE = date(2026, 6, 30)
DEADLINE_SMALL = date(2028, 6, 30)
MAX_YEARS_SINCE_PLAN = 5.0

# Signals counted over the recent months, each a feature of its own.
COUNTED_SIGNALS = (
    SignalKind.FEASIBILITY_STUDY,
    SignalKind.COUNCIL_DECISION,
    SignalKind.FUNDING_GRANTED,
    SignalKind.ROADMAP_PUBLISHED,
    SignalKind.HEAT_COMPANY_FOUNDED,
    SignalKind.JOB_POSTING,
    SignalKind.HEAT_SOURCE_PROJECT,
    SignalKind.BUDGET_ALLOCATED,
)
# What ends up as a construction tender: notices, and private builders' requests (ADR 06 §5).
TENDERED = frozenset({TenderOrigin.NOTICE, TenderOrigin.PRIVATE_REQUEST})
CAME_OUT = frozenset({TenderStatus.PUBLISHED, TenderStatus.AWARDED, TenderStatus.CANCELLED})

FEATURES: tuple[str, ...] = (
    "log_population",
    "log_density",
    "large_city",
    "plan_deadline_passed",
    "heat_plan_started",
    "heat_plan_adopted",
    "years_since_heat_plan",
    *(f"recent_{kind.value}" for kind in COUNTED_SIGNALS),
    "gas_concession_ends_soon",
    "construction_planned",
    "recent_planning_tenders",
    "recent_construction_tenders",
    "construction_tenders_before",
    "framework_ends_soon",
    "district_heating_share",
    "gas_heating_share",
    "oil_heating_share",
    "heat_pump_share",
    "multi_family_share",
    "housing_company_share",
    "old_building_share",
)


@dataclass(frozen=True, slots=True)
class Place:
    ags: str
    name: str
    population: int | None = None
    area_km2: float | None = None


@dataclass(frozen=True, slots=True)
class SignalFact:
    kind: SignalKind
    available_on: date
    occurred_on: date | None = None


@dataclass(frozen=True, slots=True)
class TenderFact:
    kind: TenderKind
    origin: TenderOrigin
    status: TenderStatus
    available_on: date
    published_on: date | None = None
    framework: bool = False
    contract_end_on: date | None = None

    @property
    def tendered(self) -> bool:
        """Put out to tender: a notice or a private request that came out."""
        return self.origin in TENDERED and self.status in CAME_OUT and self.published_on is not None


@dataclass(frozen=True, slots=True)
class MetricFact:
    metric: MetricKind
    available_on: date
    value: float


@dataclass(slots=True)
class History:
    """Everything public about the municipalities, by AGS: what features and labels are made of."""

    places: dict[str, Place]
    signals: dict[str, list[SignalFact]] = field(default_factory=dict[str, list[SignalFact]])
    tenders: dict[str, list[TenderFact]] = field(default_factory=dict[str, list[TenderFact]])
    metrics: dict[str, list[MetricFact]] = field(default_factory=dict[str, list[MetricFact]])

    @classmethod
    def of(
        cls,
        places: Iterable[Place],
        signals: Iterable[tuple[str, SignalFact]] = (),
        tenders: Iterable[tuple[str, TenderFact]] = (),
        metrics: Iterable[tuple[str, MetricFact]] = (),
    ) -> History:
        """The history of `places`; facts of a municipality not among them are left out."""
        known = {place.ags: place for place in places}
        return cls(
            places=known,
            signals=_grouped(known, signals),
            tenders=_grouped(known, tenders),
            metrics=_grouped(known, metrics),
        )

    def last_day(self) -> date | None:
        """The latest day any fact became available: how far the labels are observed."""
        days = [
            fact.available_on
            for facts in (*self.signals.values(), *self.tenders.values(), *self.metrics.values())
            for fact in facts
        ]
        return max(days, default=None)


def _grouped[F: (SignalFact, TenderFact, MetricFact)](
    known: dict[str, Place], facts: Iterable[tuple[str, F]]
) -> dict[str, list[F]]:
    grouped: defaultdict[str, list[F]] = defaultdict(list)
    for ags, fact in facts:
        if ags in known:
            grouped[ags].append(fact)
    return {
        ags: sorted(items, key=lambda fact: fact.available_on) for ags, items in grouped.items()
    }


def add_months(day: date, months: int) -> date:
    """`day` moved by whole months, at the end of a shorter month if need be."""
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    for last in (31, 30, 29, 28):
        try:
            return date(year, month, min(day.day, last))
        except ValueError:
            continue
    raise AssertionError(day)  # every month has at least 28 days


def months_between(start: date, end: date) -> float:
    """How many months from `start` to `end`, a fraction for the days; negative if before."""
    return (end.year - start.year) * 12 + (end.month - start.month) + (end.day - start.day) / 31


def quarters(first: date, last: date) -> list[date]:
    """The first days of the quarters from `first`'s quarter on, up to and including `last`."""
    day = date(first.year, (first.month - 1) // 3 * 3 + 1, 1)
    days: list[date] = []
    while day <= last:
        days.append(day)
        day = add_months(day, 3)
    return days


def features(history: History, ags: str, as_of: date) -> list[float]:
    """The features of `ags` on `as_of`, in the order of `FEATURES`."""
    place = history.places[ags]
    signals = [s for s in history.signals.get(ags, ()) if s.available_on <= as_of]
    tenders = [t for t in history.tenders.get(ags, ()) if t.available_on <= as_of]
    recent_from = add_months(as_of, -RECENT_MONTHS)
    population = place.population or 0
    deadline = DEADLINE_LARGE if population >= LARGE_CITY else DEADLINE_SMALL

    def recent(kind: SignalKind) -> float:
        return math.log1p(
            sum(1 for s in signals if s.kind is kind and s.available_on > recent_from)
        )

    adopted = [
        s.occurred_on or s.available_on for s in signals if s.kind is SignalKind.HEAT_PLAN_ADOPTED
    ]
    years_since_plan = (as_of - min(adopted)).days / 365.25 if adopted else 0.0
    out = [t for t in tenders if t.tendered and t.published_on and t.published_on <= as_of]

    def tendered(kind: TenderKind, since: date | None = None) -> float:
        return math.log1p(
            sum(
                1
                for t in out
                if t.kind is kind and (since is None or (t.published_on and t.published_on > since))
            )
        )

    return [
        math.log1p(population),
        math.log1p(population / place.area_km2) if population and place.area_km2 else 0.0,
        1.0 if population >= LARGE_CITY else 0.0,
        1.0 if as_of > deadline else 0.0,
        _any(signals, SignalKind.HEAT_PLAN_STARTED),
        1.0 if adopted else 0.0,
        min(max(years_since_plan, 0.0), MAX_YEARS_SINCE_PLAN),
        *(recent(kind) for kind in COUNTED_SIGNALS),
        1.0
        if any(
            s.kind is SignalKind.GAS_CONCESSION_ENDS
            and s.occurred_on is not None
            and as_of <= s.occurred_on <= add_months(as_of, CONCESSION_MONTHS)
            for s in signals
        )
        else 0.0,
        1.0
        if any(
            t.kind is TenderKind.CONSTRUCTION
            and t.origin is TenderOrigin.PREVIEW
            and t.status is TenderStatus.PLANNED
            for t in tenders
        )
        else 0.0,
        tendered(TenderKind.PLANNING, recent_from),
        tendered(TenderKind.CONSTRUCTION, recent_from),
        tendered(TenderKind.CONSTRUCTION),
        1.0
        if any(
            t.kind is TenderKind.CONSTRUCTION
            and t.framework
            and t.contract_end_on is not None
            and as_of < t.contract_end_on <= add_months(as_of, SOON_MONTHS)
            for t in tenders
        )
        else 0.0,
        _latest(history.metrics.get(ags, ()), MetricKind.DISTRICT_HEATING_SHARE, as_of),
        _latest(history.metrics.get(ags, ()), MetricKind.GAS_HEATING_SHARE, as_of),
        *(
            _latest(history.metrics.get(ags, ()), metric, as_of)
            for metric in (
                MetricKind.OIL_HEATING_SHARE,
                MetricKind.HEAT_PUMP_SHARE,
                MetricKind.MULTI_FAMILY_SHARE,
                MetricKind.HOUSING_COMPANY_SHARE,
                MetricKind.OLD_BUILDING_SHARE,
            )
        ),
    ]


def _any(signals: Sequence[SignalFact], kind: SignalKind) -> float:
    return 1.0 if any(s.kind is kind for s in signals) else 0.0


def _latest(metrics: Sequence[MetricFact], metric: MetricKind, as_of: date) -> float:
    available = [m for m in metrics if m.metric is metric and m.available_on <= as_of]
    return available[-1].value if available else 0.0


def next_tender(history: History, ags: str, as_of: date) -> date | None:
    """When `ags` next put a heat network's construction out to tender after `as_of`, if ever."""
    days = [
        t.published_on
        for t in history.tenders.get(ags, ())
        if t.kind is TenderKind.CONSTRUCTION
        and t.tendered
        and t.published_on
        and t.published_on > as_of
    ]
    return min(days, default=None)


def label(history: History, ags: str, as_of: date, horizon_months: int) -> bool:
    """Whether `ags` put a heat network's construction out to tender within the horizon."""
    following = next_tender(history, ags, as_of)
    return following is not None and following <= add_months(as_of, horizon_months)
