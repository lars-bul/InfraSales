from dataclasses import replace
from datetime import date
from pathlib import Path

from infrasales.projects.models import TenderKind, TenderStatus
from infrasales.sources import ted_xml
from infrasales.sources.heat import Relevance
from infrasales.sources.records import LotRecord

FIXTURES = Path(__file__).parent / "fixtures" / "ted"


def read(number: str) -> list[LotRecord]:
    return ted_xml.lots_of_xml(number, (FIXTURES / f"{number}.xml").read_text(encoding="utf-8"))


def test_an_older_award_gives_its_winner_offers_and_contract_day() -> None:
    (lot,) = read("166070-2020")

    assert lot.status is TenderStatus.AWARDED
    assert lot.notice_type == "can-standard"
    assert lot.procedure == "open"
    assert lot.offers == 4
    assert lot.awarded_on == date(2020, 3, 30)
    assert lot.relevance.reason == "code:45232140"
    (award,) = lot.awards
    assert (award.winner_name, award.post_code, award.city, award.country) == (
        "SEG Rohrbau GmbH",
        "84072",
        "Au in der Hallertau",
        "DEU",
    )


def test_an_older_contract_notice_gives_its_own_title_and_words() -> None:
    (lot,) = read("26230-2017")

    assert lot.status is TenderStatus.PUBLISHED
    assert lot.title.startswith("Lieferung und betriebsfertige Verlegung")
    assert lot.relevance == Relevance(heat_network=True, reason="code:45232140")
    assert lot.kind is TenderKind.CONSTRUCTION


def test_a_form_it_does_not_read_gives_nothing() -> None:
    xml = '<TED_EXPORT xmlns="x"><FORM_SECTION><F14_2014 LG="DE"/></FORM_SECTION></TED_EXPORT>'

    assert ted_xml.lots_of_xml("1-2017", xml) == []


def test_the_xml_reading_keeps_the_place_only_the_api_gives() -> None:
    (xml_lot,) = read("26230-2017")
    api_lot = replace(xml_lot, place_nuts="DE21H")
    without = replace(xml_lot, place_nuts=None)

    assert [lot.place_nuts for lot in ted_xml.merged([api_lot], [without])] == ["DE21H"]
    assert ted_xml.merged([api_lot], []) == [api_lot]
