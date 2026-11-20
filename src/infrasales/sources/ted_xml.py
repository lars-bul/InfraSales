"""Older TED notices (before eForms, schema R2.0.9) read from their XML: titles, lots, awards.

The search API gives such notices without their own titles, lots or winners; their XML
(`https://ted.europa.eu/en/notice/<number>/xml`) has them: the form (F01 prior information, F02
contract notice, F03 award, F05/F06 for utilities, F15 voluntary transparency), its contracting
body, the object with its lots, the procedure, and per lot the award with the tenders received,
the contractors and the value. Tags are read by their local names, whatever the namespace.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import replace
from datetime import date

from infrasales.projects.models import TenderStatus
from infrasales.sources.heat import kind_of, relevance
from infrasales.sources.records import AwardRecord, LotRecord, months

XML_URL = "https://ted.europa.eu/en/notice/{number}/xml"
NOTICE_URL = "https://ted.europa.eu/de/notice/-/detail/{number}"

# Forms by what they say: prior information, a call for competition, a result.
PIN_FORMS = frozenset({"F01", "F04", "F16", "F21_PIN"})
CN_FORMS = frozenset({"F02", "F05", "F17", "F21", "F22", "F24"})
CAN_FORMS = frozenset({"F03", "F06", "F15", "F18", "F25"})
PROCEDURES = {
    "PT_OPEN": "open",
    "PT_RESTRICTED": "restricted",
    "PT_NEGOTIATED_WITH_PRIOR_CALL": "neg-w-call",
    "PT_COMPETITIVE_NEGOTIATION": "neg-w-call",
    "PT_COMPETITIVE_DIALOGUE": "comp-dial",
    "PT_INNOVATION_PARTNERSHIP": "innovation",
    "PT_AWARD_CONTRACT_WITHOUT_CALL": "neg-wo-call",
    "PT_AWARD_CONTRACT_WITHOUT_PUBLICATION": "neg-wo-call",
    "PT_NEGOTIATED_WITHOUT_PUBLICATION": "neg-wo-call",
}
NATURES = {"WORKS": "works", "SUPPLIES": "supplies", "SERVICES": "services"}
SIZE_FLAGS = {"SME": "sme", "NO_SME": "large"}


def _local(tag: str) -> str:
    return tag.rpartition("}")[2]


def _strip(root: ET.Element) -> ET.Element:
    for element in root.iter():
        element.tag = _local(element.tag)
    return root


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    text = " ".join(" ".join(element.itertext()).split())
    return text or None


def _code(element: ET.Element | None) -> str | None:
    return None if element is None else element.get("CODE")


def _day(text: str | None) -> date | None:
    if not text:
        return None
    match = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", text)
    return date(int(match[1]), int(match[2]), int(match[3])) if match else None


def _amount(element: ET.Element | None) -> int | None:
    if element is None or element.text is None:
        return None
    try:
        value = float(element.text.replace(" ", "").replace(",", "."))
    except ValueError:
        return None
    return round(value) if value >= 1 else None


def _form(root: ET.Element) -> ET.Element | None:
    """The notice's form in German, else its first."""
    section = root.find("FORM_SECTION")
    if section is None or len(section) == 0:
        return None
    for form in section:
        if form.get("LG") == "DE":
            return form
    return section[0]


def _form_name(form: ET.Element) -> str:
    name = form.tag.split("_")[0]
    return (
        "F21_PIN"
        if name == "F21" and form.find(".//NOTICE[@TYPE='PRI_ONLY']") is not None
        else name
    )


def _awards(form: ET.Element) -> Iterator[tuple[str | None, ET.Element]]:
    for award in form.iter("AWARD_CONTRACT"):
        yield _text(award.find("LOT_NO")), award


def lots_of_xml(number: str, xml: str) -> list[LotRecord]:  # one form read field by field
    """An older notice's lots, from its XML; none for a corrigendum, a change or a form not read."""
    root = _strip(ET.fromstring(xml))  # noqa: S314  # TED's own XML, read in a parser with expat's limits
    form = _form(root)
    if form is None:
        return []
    name = _form_name(form)
    published = _day(_text(root.find(".//REF_OJS/DATE_PUB"))) or _day(
        _text(root.find(".//DATE_PUB"))
    )
    if published is None:
        return []
    body = form.find(".//ADDRESS_CONTRACTING_BODY")
    obj = form.find("OBJECT_CONTRACT")
    if obj is None:
        return []
    main = _code(obj.find("CPV_MAIN/CPV_CODE"))
    contract_type = obj.find("TYPE_CONTRACT")
    nature = NATURES.get((contract_type.get("CTYPE") if contract_type is not None else "") or "")
    title = _text(obj.find("TITLE"))
    description = _text(obj.find("SHORT_DESCR"))
    procedure_element = form.find("PROCEDURE")
    procedure = None
    framework = False
    deadline = None
    if procedure_element is not None:
        procedure = next(
            (PROCEDURES[c.tag] for c in procedure_element if c.tag in PROCEDURES), None
        )
        framework = procedure_element.find("FRAMEWORK") is not None
        deadline = _day(_text(procedure_element.find("DATE_RECEIPT_TENDERS")))
    items = obj.findall("OBJECT_DESCR") or [obj]
    lot_count = len(items) if obj.find("LOT_DIVISION") is not None else 1
    awards = dict(_awards(form))
    records: list[LotRecord] = []
    for item in items:
        lot = _text(item.find("LOT_NO"))
        lot_title = _text(item.find("TITLE")) or title or number
        lot_description = _text(item.find("SHORT_DESCR")) or description
        codes = tuple(
            dict.fromkeys(filter(None, [main, *[_code(c) for c in item.iter("CPV_CODE")]]))
        )
        criteria = [c.tag for c in item.iter() if c.tag in {"AC_PRICE", "AC_QUALITY", "AC_COST"}]
        duration = item.find("DURATION")
        award = awards.get(lot)
        if award is None and len(awards) == 1:
            award = next(iter(awards.values()))
        status, award_records, offers, value, awarded_on = _result(name, award)
        if status is None:
            return []
        records.append(
            LotRecord(
                source="ted",
                notice_id=number,
                notice_type=_notice_type(name),
                procedure_ref=None,
                lot=lot,
                title=lot_title[:500],
                kind=kind_of(nature, [main] if main else codes),
                status=status,
                published_on=published,
                relevance=relevance(
                    [main] if main else (), codes, [lot_title, title], [lot_description]
                ),
                cpv=codes,
                description=lot_description,
                buyer_name=_text(body.find("OFFICIALNAME")) if body is not None else None,
                buyer_post_code=_text(body.find("POSTAL_CODE")) if body is not None else None,
                buyer_city=_text(body.find("TOWN")) if body is not None else None,
                place_nuts=_code(item.find("NUTS"))
                or (_code(body.find("NUTS")) if body is not None else None),
                place_city=_text(item.find("MAIN_SITE")),
                procedure=procedure,
                lots=lot_count,
                framework=framework,
                duration_months=months(float(duration.text), duration.get("TYPE"))
                if duration is not None and duration.text and duration.text.strip().isdigit()
                else None,
                price_only=(set(criteria) <= {"AC_PRICE"}) if criteria else None,
                deadline_on=deadline,
                awarded_on=awarded_on,
                estimated_value_eur=_amount(item.find("VAL_OBJECT"))
                or _amount(obj.find("VAL_ESTIMATED_TOTAL")),
                award_value_eur=value,
                offers=offers,
                awards=award_records,
                url=NOTICE_URL.format(number=number),
            )
        )
    return records


def _notice_type(form: str) -> str:
    if form in PIN_FORMS:
        return "pin-only"
    if form in CN_FORMS:
        return "cn-standard"
    return "veat" if form == "F15" else "can-standard"


def _result(
    form: str, award: ET.Element | None
) -> tuple[TenderStatus | None, tuple[AwardRecord, ...], int | None, int | None, date | None]:
    """A lot's status and result: winners, tenders received, value, the contract's day."""
    if form in PIN_FORMS:
        return TenderStatus.PLANNED, (), None, None, None
    if form in CN_FORMS:
        return TenderStatus.PUBLISHED, (), None, None, None
    if form not in CAN_FORMS:
        return None, (), None, None, None
    if award is None or award.find("AWARDED_CONTRACT") is None:
        return TenderStatus.CANCELLED, (), None, None, None
    contract = award.find("AWARDED_CONTRACT")
    assert contract is not None  # noqa: S101  # found just above
    received = _text(contract.find(".//NB_TENDERS_RECEIVED"))
    winners = tuple(
        AwardRecord(
            winner_name=name,
            post_code=_text(address.find("POSTAL_CODE")),
            city=_text(address.find("TOWN")),
            country=_country(address.find("COUNTRY")),
            size=_size(contractor),
        )
        for contractor in contract.iter("CONTRACTOR")
        if (address := contractor.find("ADDRESS_CONTRACTOR")) is not None
        and (name := _text(address.find("OFFICIALNAME")))
    )
    value = _amount(contract.find(".//VAL_TOTAL"))
    concluded = _day(_text(contract.find("DATE_CONCLUSION_CONTRACT")))
    offers = int(received) if received and received.isdigit() else None
    return TenderStatus.AWARDED, winners, offers, value, concluded


ISO2_TO_ISO3 = {"DE": "DEU", "AT": "AUT", "CH": "CHE", "NL": "NLD", "DK": "DNK", "PL": "POL",
                "CZ": "CZE", "FR": "FRA", "BE": "BEL", "LU": "LUX", "IT": "ITA"}  # fmt: skip


def _country(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    code = element.get("VALUE") or ""
    return ISO2_TO_ISO3.get(code, code or None)


def _size(contractor: ET.Element) -> str | None:
    for flag, size in SIZE_FLAGS.items():
        if contractor.find(flag) is not None:
            return size
    return None


def merged(api: list[LotRecord], xml: list[LotRecord]) -> list[LotRecord]:
    """The notice as its XML reads it, keeping what only the API gives (the place's NUTS code)."""
    if not xml:
        return api
    nuts = next((record.place_nuts for record in api if record.place_nuts), None)
    return [replace(record, place_nuts=record.place_nuts or nuts) for record in xml]
