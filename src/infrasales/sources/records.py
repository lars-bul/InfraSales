"""A lot of a notice, read the same way from any source.

TED and the Datenservice Öffentlicher Einkauf both become `LotRecord`s: what
`infrasales.sources.store` merges into the tenders.
"""

from dataclasses import dataclass, field
from datetime import date

from infrasales.projects.models import TenderKind, TenderStatus
from infrasales.sources.heat import Relevance

DEFAULT_LOT = "LOT-0000"  # eForms' name for the one lot of a procedure without lots


@dataclass(frozen=True, slots=True)
class AwardRecord:
    winner_name: str
    winner_identifier: str | None = None
    post_code: str | None = None
    city: str | None = None
    country: str | None = None
    size: str | None = None  # micro, small, medium, large
    value_eur: int | None = None


@dataclass(frozen=True, slots=True)
class LotRecord:
    source: str  # "ted" or "doe"
    notice_id: str  # TED's publication number, the service's notice id
    notice_type: str  # eForms notice subtype, e.g. "cn-standard", "can-standard", "pin-only"
    procedure_ref: str | None  # the eForms procedure id its notices share
    lot: str | None
    title: str
    kind: TenderKind
    status: TenderStatus
    published_on: date
    relevance: Relevance
    cpv: tuple[str, ...] = ()
    description: str | None = None
    buyer_name: str | None = None
    buyer_post_code: str | None = None
    buyer_city: str | None = None
    place_post_code: str | None = None
    place_city: str | None = None
    place_nuts: str | None = None
    procedure: str | None = None  # open, restricted, neg-w-call, neg-wo-call, …
    lots: int | None = None
    framework: bool = False
    duration_months: float | None = None
    price_only: bool | None = None
    sme_suitable: bool | None = None
    deadline_on: date | None = None
    awarded_on: date | None = None
    contract_end_on: date | None = None
    estimated_value_eur: int | None = None
    award_value_eur: int | None = None
    lowest_offer_eur: int | None = None
    highest_offer_eur: int | None = None
    offers: int | None = None
    awards: tuple[AwardRecord, ...] = field(default_factory=tuple[AwardRecord, ...])
    url: str | None = None

    @property
    def key(self) -> str:
        """What its tender is found by: the procedure and lot, else the notice and lot."""
        if self.procedure_ref:
            return f"proc:{self.procedure_ref}:{self.lot or DEFAULT_LOT}"
        return f"{self.source}:{self.notice_id}:{self.lot or DEFAULT_LOT}"


def status_of(notice_type: str, *, awarded: bool) -> TenderStatus | None:
    """The status a notice of this eForms subtype gives its lots.

    None for a notice that says nothing new: a corrigendum, a modification.
    """
    if notice_type.startswith("pin"):
        return TenderStatus.PLANNED
    if notice_type.startswith(("cn", "qu", "subco", "pmc")):
        return TenderStatus.PUBLISHED
    if notice_type.startswith(("can", "veat")):
        return TenderStatus.AWARDED if awarded else TenderStatus.CANCELLED
    return None


def months(value: float | None, unit: str | None) -> float | None:
    """A duration in months, from a value and its eForms unit (DAY, WEEK, MONTH, YEAR)."""
    if value is None or unit is None:
        return None
    factor = {"DAY": 1 / 30.4375, "WEEK": 7 / 30.4375, "MONTH": 1.0, "YEAR": 12.0}.get(unit.upper())
    return None if factor is None else round(value * factor, 2)
