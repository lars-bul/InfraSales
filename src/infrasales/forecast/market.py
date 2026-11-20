"""How a heat network contract is likely put out to tender, and how many will bid: from past awards.

The form of an award (procedure, lots, framework agreement, price alone or quality too, duration,
value) and its competition (offers received) are read from the tenders a buyer put out before.
A buyer with too few is described by the tenders of its municipality, then of its Land, then of
all: the nearest group with enough tenders speaks for it (`profile`), and says which it is.
"""

import statistics
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

MIN_TENDERS = 3  # a group with fewer does not speak for a buyer


@dataclass(frozen=True, slots=True)
class PastTender:
    """What a past tender says about the form and competition of an award."""

    buyer: str  # normalised name
    ags: str | None
    procedure: str | None
    lots: int | None
    framework: bool
    price_only: bool | None
    duration_months: float | None
    value_eur: int | None  # awarded, else estimated
    offers: int | None
    sme_suitable: bool | None


@dataclass(frozen=True, slots=True)
class FormProfile:
    """The likely form of the next award, and the competition, with the group it comes from."""

    basis: str  # "buyer", "municipality", "land" or "all"
    tenders: int
    procedure: str | None  # the most frequent
    procedure_share: float | None  # how often it was that
    lots_median: float | None
    framework_share: float
    price_only_share: float | None
    duration_months_median: float | None
    value_eur_median: int | None
    offers_median: float | None
    offers_known: int  # tenders that told their offers
    sme_suitable_share: float | None

    def as_json(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__slots__}


def _median(values: Sequence[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _share(flags: Sequence[bool]) -> float | None:
    return round(sum(flags) / len(flags), 3) if flags else None


def describe(basis: str, tenders: Sequence[PastTender]) -> FormProfile:
    procedures = Counter(t.procedure for t in tenders if t.procedure)
    top = procedures.most_common(1)
    offers = [t.offers for t in tenders if t.offers is not None]
    values = [t.value_eur for t in tenders if t.value_eur]
    median_value = _median(values)
    return FormProfile(
        basis=basis,
        tenders=len(tenders),
        procedure=top[0][0] if top else None,
        procedure_share=round(top[0][1] / procedures.total(), 3) if top else None,
        lots_median=_median([t.lots for t in tenders if t.lots]),
        framework_share=round(sum(t.framework for t in tenders) / len(tenders), 3)
        if tenders
        else 0.0,
        price_only_share=_share([t.price_only for t in tenders if t.price_only is not None]),
        duration_months_median=_median([t.duration_months for t in tenders if t.duration_months]),
        value_eur_median=round(median_value) if median_value is not None else None,
        offers_median=_median(offers),
        offers_known=len(offers),
        sme_suitable_share=_share([t.sme_suitable for t in tenders if t.sme_suitable is not None]),
    )


def profile(tenders: Sequence[PastTender], *, buyer: str | None, ags: str | None) -> FormProfile:
    """The nearest group with enough tenders: the buyer's, the municipality's, the Land's, all."""
    groups: list[tuple[str, Callable[[PastTender], bool]]] = []
    if buyer:
        groups.append(("buyer", lambda t: t.buyer == buyer))
    if ags:
        groups.append(("municipality", lambda t: t.ags == ags))
        groups.append(("land", lambda t: (t.ags or "")[:2] == ags[:2]))
    for basis, belongs in groups:
        chosen = [t for t in tenders if belongs(t)]
        if len(chosen) >= MIN_TENDERS:
            return describe(basis, chosen)
    return describe("all", tenders)
