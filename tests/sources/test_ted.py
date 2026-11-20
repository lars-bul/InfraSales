import json
from datetime import date
from pathlib import Path

import httpx2

from infrasales.projects.models import TenderKind, TenderStatus
from infrasales.sources import ted

FIXTURES = Path(__file__).parent / "fixtures" / "ted"


def notices() -> dict[str, ted.Notice]:
    return {str(n["publication-number"]): n for n in ted.read_pages(FIXTURES)}


def test_an_eforms_award_gives_its_lot_with_its_winner() -> None:
    (lot,) = ted.lots_of(notices()["687751-2023"])

    assert (lot.status, lot.lot, lot.place_nuts) == (TenderStatus.AWARDED, "LOT-0000", "DE21D")
    assert (lot.procedure_ref or "").startswith("6d9adca6-")
    assert [a.winner_name for a in lot.awards] == ["Nachwärmeversorung Passionswiese GmbH"]
    assert lot.relevance.reason == "heat-supply"  # heat bought, no network built
    assert lot.url == "https://ted.europa.eu/de/notice/-/detail/687751-2023"


def test_a_contract_notice_gives_each_of_its_lots() -> None:
    lots = ted.lots_of(notices()["675934-2023"])

    assert [lot.lot for lot in lots] == [f"LOT-000{i}" for i in range(1, 6)]
    assert {(lot.status, lot.kind, lot.procedure) for lot in lots} == {
        (TenderStatus.PUBLISHED, TenderKind.PLANNING, "neg-w-call")
    }
    assert len({lot.key for lot in lots}) == len(lots)
    assert all(lot.lots == len(lots) for lot in lots)


def test_an_older_notice_names_its_main_code_in_its_title() -> None:
    (lot,) = ted.lots_of(notices()["436093-2016"])

    assert (lot.procedure_ref, lot.kind, lot.place_nuts) == (None, TenderKind.CONSTRUCTION, "DE212")
    assert lot.published_on == date(2016, 12, 10)
    assert lot.relevance.reason == "secondary-code"  # its XML tells more (`ted_xml`)


def test_a_prior_information_notice_is_planned_and_a_corrigendum_says_nothing_new() -> None:
    assert {lot.status for lot in ted.lots_of(notices()["444102-2016"])} == {TenderStatus.PLANNED}
    assert ted.lots_of(notices()["3797-2017"]) == []


def test_older_procedure_codes_are_named_as_eforms_names_them() -> None:
    assert ted.procedure_of("1") == "open"
    assert ted.procedure_of("T") == "neg-wo-call"
    assert ted.procedure_of("9") is None
    assert ted.procedure_of("open") == "open"
    assert ted.procedure_of(None) is None


def test_the_query_asks_for_german_heat_network_notices_since_a_day() -> None:
    query = ted.query_since(date(2024, 1, 31))

    assert query.endswith("publication-date>=20240131")
    assert "place-of-performance=DEU" in query


def test_search_pages_follow_the_iteration_token_until_no_notice_is_left() -> None:
    asked: list[dict[str, object]] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        asked.append(body)
        if "iterationNextToken" not in body:
            return httpx2.Response(
                200,
                json={"notices": [{"publication-number": "1-2024"}], "iterationNextToken": "t1"},
            )
        return httpx2.Response(200, json={"notices": [], "iterationNextToken": "t2"})

    with httpx2.Client(transport=httpx2.MockTransport(answer)) as client:
        pages = list(ted.search_pages(client, "q", ("publication-number",)))

    assert len(pages) == 2
    assert asked[0]["paginationMode"] == "ITERATION"
    assert asked[1]["iterationNextToken"] == "t1"
