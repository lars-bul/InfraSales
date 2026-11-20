"""Early signals in the notices: what a municipality tenders before its heat network.

Before a heat network is built, its municipality or utility commissions work that is itself put
out to tender, with a date: the municipal heat plan, a feasibility study or transformation plan,
a heat source (a large heat pump, waste heat, geothermal heat, a heat store). Every such notice in
the Datenservice's monthly exports (all German notices) and in TED becomes a dated signal of
its place, known from its publication day.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date

from infrasales.projects.models import SignalKind
from infrasales.sources.records import LotRecord

# The kinds of commission, by the words of a title (lower case), the first that matches decides.
PATTERNS: tuple[tuple[SignalKind, re.Pattern[str]], ...] = (
    (
        SignalKind.HEAT_PLAN_STARTED,
        re.compile(r"wärmeplanung|wärmeplan\b|wärmeleitplan|\bkwp\b|wärmeplans|wärmeplanes"),
    ),
    (
        SignalKind.FEASIBILITY_STUDY,
        re.compile(
            r"transformationsplan|machbarkeitsstudie[^.]{0,80}(wärme|netz|energie)|"
            r"(wärme|netz|energie)[^.]{0,80}machbarkeitsstudie|\bbew\b|wärmenetzstudie|"
            r"energetisches quartierskonzept|quartierskonzept"
        ),
    ),
    (
        SignalKind.HEAT_SOURCE_PROJECT,
        re.compile(
            r"großwärmepumpe|grosswärmepumpe|flusswärmepumpe|abwasserwärme|abwärme|geothermie|"
            r"solarthermieanlage|solarthermie-anlage|freiflächensolarthermie|wärmespeicher|"
            r"power[- ]to[- ]heat|elektrodenkessel|biomasseheizwerk|holzheizwerk|heizwerk"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class NoticeSignal:
    kind: SignalKind
    ref: str  # one per notice and kind: loading again updates
    available_on: date
    title: str
    url: str | None
    post_code: str | None
    city: str | None
    buyer: str | None
    buyer_post_code: str | None
    buyer_city: str | None
    nuts: str | None


def kind_of(text: str) -> SignalKind | None:
    lowered = text.lower()
    return next((kind for kind, pattern in PATTERNS if pattern.search(lowered)), None)


def signals_of(lots: Iterable[LotRecord]) -> Iterator[NoticeSignal]:
    """One signal per notice whose title names an early step; its lots tell the same."""
    seen: set[str] = set()
    for lot in lots:
        kind = kind_of(lot.title)
        if kind is None:
            continue
        ref = f"{lot.source}:{lot.notice_id}:{kind.value}"
        if ref in seen:
            continue
        seen.add(ref)
        yield NoticeSignal(
            kind=kind,
            ref=ref,
            available_on=lot.published_on,
            title=lot.title,
            url=lot.url,
            post_code=lot.place_post_code,
            city=lot.place_city,
            buyer=lot.buyer_name,
            buyer_post_code=lot.buyer_post_code,
            buyer_city=lot.buyer_city,
            nuts=lot.place_nuts,
        )
