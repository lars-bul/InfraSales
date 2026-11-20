"""TED, the EU's Tenders Electronic Daily: its search API, and its notices read as lots.

The search API (`https://api.ted.europa.eu/v3/notices/search`, open, no key) answers an expert
query with the fields asked for, flattened: a field of a notice's lots is a list in lot order.
eForms notices (from late 2023) carry the procedure id, lots, results and winners; older ones
only the notice's basics, their awards being in the notice's XML (`infrasales.sources.ted_xml`).

The query takes every German notice that may concern a heat network, by its codes or its title;
`infrasales.sources.heat` decides afterwards, and keeps the reason.
"""

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, cast

import httpx2

from infrasales.projects.models import TenderStatus
from infrasales.sources.heat import NETWORK_CODES, kind_of, relevance
from infrasales.sources.records import AwardRecord, LotRecord, months, status_of

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
NOTICE_URL = "https://ted.europa.eu/de/notice/-/detail/{number}"
MAX_FIELDS_PER_PAGE = 9000  # the API allows 10,000, counting a few of its own

FIELDS = (
    "publication-number", "notice-type", "publication-date", "notice-title", "procedure-type",
    "procedure-identifier", "contract-nature-main-proc", "classification-cpv",
    "main-classification-lot", "buyer-name", "buyer-city", "buyer-post-code", "buyer-country-sub",
    "buyer-legal-type", "buyer-identifier", "place-of-performance",
    "place-of-performance-subdiv-lot",
    "place-of-performance-city-lot", "place-of-performance-post-code-lot", "identifier-lot",
    "title-lot", "framework-agreement-lot", "contract-framework-agreement", "lots-max-allowed-proc",
    "duration-period-value-lot", "duration-period-unit-lot", "contract-duration-start-date-lot",
    "contract-duration-end-date-lot", "estimated-value-lot", "estimated-value-proc",
    "estimated-value-cur-lot", "result-value-lot", "total-value", "tender-value",
    "tender-value-lowest", "tender-value-highest", "deadline-receipt-tender-date-lot",
    "winner-name", "winner-city", "winner-post-code", "winner-country", "winner-size",
    "winner-identifier", "winner-decision-date", "contract-conclusion-date",
    "received-submissions-type-code", "received-submissions-type-val", "sme-lot",
    "award-criterion-type-lot", "award-criterion-number-weight-lot",
    "previous-planning-identifier-lot", "result-lot-identifier", "tender-lot-identifier",
    "subcontracting", "title-proc", "description-lot", "dispatch-date",
)  # fmt: skip

HEAT_QUERY = (
    "place-of-performance=DEU AND (classification-cpv IN (45232140 45251250 45232142 09323000)"
    ' OR notice-title~"Fernwärme" OR notice-title~"Nahwärme" OR notice-title~"Wärmenetz"'
    ' OR notice-title~"Wärmeleitung" OR notice-title~"Wärmeversorgung")'
)
NUTS3_LENGTH = 5  # e.g. "DE125"
LANGUAGES = ("deu", "mul", "eng")  # the text read from a multilingual field, in this order

type Notice = Mapping[str, Any]


def query_since(day: date) -> str:
    return f"{HEAT_QUERY} AND publication-date>={day:%Y%m%d}"


def search_pages(
    client: httpx2.Client, query: str, fields: Sequence[str] = FIELDS
) -> Iterator[dict[str, Any]]:
    """Every page of the query's answer, in the API's iteration mode (no limit on notices)."""
    body: dict[str, Any] = {
        "query": query,
        "fields": list(fields),
        "limit": MAX_FIELDS_PER_PAGE // len(fields),
        "paginationMode": "ITERATION",
    }
    while True:
        response = client.post(SEARCH_URL, json=body)
        response.raise_for_status()
        page: dict[str, Any] = response.json()
        yield page
        token = page.get("iterationNextToken")
        if not page.get("notices") or not token:
            return
        body["iterationNextToken"] = token


def read_pages(folder: Path) -> Iterator[Notice]:
    """The notices of the pages stored in `folder` (`page-0001.json`, …), in order."""
    for path in sorted(folder.glob("page-*.json")):
        yield from json.loads(path.read_text(encoding="utf-8")).get("notices", [])


def _texts(value: object) -> list[str]:
    """A field's texts: a multilingual one's in the first language there, a list as it is."""
    if isinstance(value, Mapping):
        texts = cast("Mapping[str, object]", value)
        for language in (*LANGUAGES, *sorted(texts)):
            if language in texts:
                return _texts(texts[language])
        return []
    if isinstance(value, list):
        return [str(item) for item in cast("list[object]", value) if item is not None]
    return [] if value is None else [str(value)]


def _text(value: object) -> str | None:
    texts = _texts(value)
    return texts[0].strip() if texts else None


def _at(value: object, index: int, count: int) -> str | None:
    """The value of the `index`th of `count` lots: by position when there is one per lot."""
    texts = _texts(value)
    if len(texts) == count:
        return texts[index].strip()
    return texts[0].strip() if texts else None


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text[:10]) if text and len(text) >= 10 else None  # noqa: PLR2004


def _amount(text: object) -> int | None:
    try:
        value = float(str(text))
    except ValueError:
        return None
    return round(value) if value >= 1 else None  # 0 or 0.01: the value was withheld


def _offers(notice: Notice, index: int, count: int) -> int | None:
    """Tenders received for a lot: the "tenders" entries of the received submissions, by lot."""
    codes = _texts(notice.get("received-submissions-type-code"))
    values = _texts(notice.get("received-submissions-type-val"))
    counts = [v for c, v in zip(codes, values, strict=False) if c == "tenders"]
    if not counts:
        return None
    chosen = counts[index] if len(counts) == count else counts[0]
    return int(chosen) if chosen.isdigit() else None


def _awards(notice: Notice, lot: str, lots: Sequence[str]) -> tuple[AwardRecord, ...]:
    """The winners of a lot: by the result's lot ids when they line up, else all for one lot."""
    names = _texts(notice.get("winner-name"))
    if not names:
        return ()
    result_lots = _texts(notice.get("result-lot-identifier"))
    per_winner = len(result_lots) == len(names)
    awards: list[AwardRecord] = []
    for i, name in enumerate(names):
        if per_winner and result_lots[i] != lot:
            continue
        if not per_winner and len(lots) > 1 and lot != lots[0]:
            continue
        awards.append(
            AwardRecord(
                winner_name=name.strip(),
                winner_identifier=_at(notice.get("winner-identifier"), i, len(names)),
                post_code=_at(notice.get("winner-post-code"), i, len(names)),
                city=_at(notice.get("winner-city"), i, len(names)),
                country=_at(notice.get("winner-country"), i, len(names)),
                size=_at(notice.get("winner-size"), i, len(names)),
            )
        )
    return tuple({award.winner_name: award for award in awards}.values())


def lots_of(notice: Notice) -> list[LotRecord]:
    """A notice read as its lots; none for a corrigendum or a change, which add nothing to keep."""
    notice_type = str(notice.get("notice-type") or "")
    number = str(notice["publication-number"])
    published = _day(str(notice.get("publication-date") or ""))
    lots = _texts(notice.get("identifier-lot")) or [None]
    count = len(lots)
    eforms = "procedure-identifier" in notice  # older notices: no lots, results or winners here
    has_winner = bool(_texts(notice.get("winner-name"))) or notice_type.startswith("veat")
    status = status_of(notice_type, awarded=has_winner or not eforms)
    if status is None or published is None:
        return []
    codes = tuple(dict.fromkeys(_texts(notice.get("classification-cpv"))))
    nature = _text(notice.get("contract-nature-main-proc"))
    procedure_title = _text(notice.get("title-proc"))
    # An older notice's "title" is its country, town and main code's name, not words of its own.
    notice_title = _text(notice.get("notice-title"))
    places = [p for p in _texts(notice.get("place-of-performance")) if len(p) == NUTS3_LENGTH]
    framework_flags = _texts(notice.get("framework-agreement-lot"))
    weights = _texts(notice.get("award-criterion-type-lot"))
    records: list[LotRecord] = []
    for i, lot in enumerate(lots):
        own_title = _at(notice.get("title-lot"), i, count) or procedure_title
        title = own_title or notice_title or number
        description = _at(notice.get("description-lot"), i, count)
        main_code = _at(notice.get("main-classification-lot"), i, count)
        lot_codes = (main_code,) if main_code else _legacy_main(notice_title, codes)
        framework_flag = (
            framework_flags[i] if len(framework_flags) == count else (framework_flags or [None])[0]
        )
        framework = (framework_flag not in {None, "none"}) or any(
            v == "True" for v in _texts(notice.get("contract-framework-agreement"))
        )
        lowest = _at(notice.get("tender-value-lowest"), i, count)
        highest = _at(notice.get("tender-value-highest"), i, count)
        awards = _awards(notice, lot, [x or "" for x in lots]) if lot else _awards(notice, "", [""])
        value = _amount(notice.get("total-value")) if count == 1 else None
        records.append(
            LotRecord(
                source="ted",
                notice_id=number,
                notice_type=notice_type,
                procedure_ref=_text(notice.get("procedure-identifier")),
                lot=lot,
                title=title[:500],
                kind=kind_of(nature, lot_codes or codes),
                status=status,
                published_on=published,
                relevance=relevance(lot_codes, codes, [own_title, procedure_title], [description]),
                cpv=codes,
                description=description,
                buyer_name=_text(notice.get("buyer-name")),
                buyer_post_code=_text(notice.get("buyer-post-code")),
                buyer_city=_text(notice.get("buyer-city")),
                place_post_code=_at(notice.get("place-of-performance-post-code-lot"), i, count),
                place_city=_at(notice.get("place-of-performance-city-lot"), i, count),
                place_nuts=_at(notice.get("place-of-performance-subdiv-lot"), i, count)
                or (places[0] if places else None),
                procedure=procedure_of(_text(notice.get("procedure-type"))),
                lots=count if lots != [None] else None,
                framework=framework,
                duration_months=_duration(notice, i, count),
                price_only=_price_only(weights) if weights else None,
                sme_suitable=_flag(_at(notice.get("sme-lot"), i, count)),
                deadline_on=_day(_at(notice.get("deadline-receipt-tender-date-lot"), i, count)),
                awarded_on=_day(_text(notice.get("winner-decision-date")))
                or _day(_text(notice.get("contract-conclusion-date"))),
                contract_end_on=_day(_at(notice.get("contract-duration-end-date-lot"), i, count)),
                estimated_value_eur=_amount(_at(notice.get("estimated-value-lot"), i, count))
                or (_amount(notice.get("estimated-value-proc")) if count == 1 else None),
                award_value_eur=(_amount(_at(notice.get("tender-value"), i, count)) or value)
                if status is TenderStatus.AWARDED
                else None,
                lowest_offer_eur=_amount(lowest) if lowest else None,
                highest_offer_eur=_amount(highest) if highest else None,
                offers=_offers(notice, i, count),
                awards=awards,
                url=NOTICE_URL.format(number=number),
            )
        )
    return records


# The main code's name in an older notice's title ("Deutschland-Ulm: Bau von Fernheizzentralen").
NETWORK_LABELS = re.compile(
    r"fernheiz|wärmeübertragungsanlage|wärmeübergabestation|fernwärmeleitung", re.IGNORECASE
)


def _legacy_main(title: str | None, codes: Sequence[str]) -> tuple[str, ...]:
    """An older notice's main code: a network code when its title names one, else its first code."""
    label = (title or "").partition(":")[2]
    if NETWORK_LABELS.search(label):
        network = [code for code in codes if code[:8] in NETWORK_CODES]
        if network:
            return (network[0],)
    return tuple(codes[:1])


# TED's codes for older notices' procedure types, as eForms names them; others are kept as given.
LEGACY_PROCEDURES = {
    "1": "open",
    "2": "restricted",
    "3": "restricted",  # accelerated
    "4": "neg-w-call",  # negotiated with a call for competition
    "6": "neg-w-call",  # accelerated negotiated
    "B": "neg-w-call",  # competitive negotiation
    "C": "comp-dial",
    "T": "neg-wo-call",  # negotiated without a call
    "V": "neg-wo-call",  # award without prior publication
}


def procedure_of(code: str | None) -> str | None:
    """The procedure type as eForms names it: an older notice's code translated, "9" dropped."""
    if code is None or code == "9":
        return None
    return LEGACY_PROCEDURES.get(code, code)


def _duration(notice: Notice, index: int, count: int) -> float | None:
    value = _at(notice.get("duration-period-value-lot"), index, count)
    unit = _at(notice.get("duration-period-unit-lot"), index, count)
    if value is not None:
        try:
            return months(float(value), unit)
        except ValueError:
            return None
    start = _day(_at(notice.get("contract-duration-start-date-lot"), index, count))
    end = _day(_at(notice.get("contract-duration-end-date-lot"), index, count))
    if start and end and end >= start:
        return round((end - start).days / 30.4375, 2)
    return None


def _price_only(types: Sequence[str]) -> bool:
    return all(kind == "price" for kind in types)


def _flag(text: str | None) -> bool | None:
    return None if text is None else text == "True"
