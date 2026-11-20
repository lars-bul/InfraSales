# ruff: noqa: E501, ISC004  # pages of the Drucksache, as its text runs
from infrasales.sources.bew import FundedProject, parse

PAGES = [
    "Antwort der Bundesregierung … Tabelle 2* …",
    "Anlage 1 \nLfd. Nr. Firma Projektort Bundesland Fördersumme in Euro\n"
    "1 OTTO FUCHS KG 58540 Meinerzhagen Nordrhein-\nWestfalen 75.056,00",
    "Anlage 2 \nDrucksache 20/13728 - 1 - Deutscher Bundestag\n"
    "Lfd. Nr. Antragsteller Projekt PLZ Ort Bundesland Fördersumme in Euro\n"
    "1 Nahwärme Hausen GmbH Nahwärmenetz Hausen 91353 Hausen Bayern 187.827,43 \n"
    "2 \nLübbener Wohnungsbaugesellschaft \nmbH \nWärmenetz Quartier Puschkinstraße 15907 Lübben Brandenburg 203.234,56\n"
    "3 Stadtwerke Tübingen GmbH Transformationsplan Netzverbund Süd 72072 Tübingen Baden-\nWürttemberg 1.109.969,56",
    "Anlage 3 \n1 STADT WEINHEIM KfW_444_A.1 69469 WEINHEIM Baden-Württemberg 9.600,00",
]


def test_the_rows_of_anlage_2_are_read_with_their_place_and_grant() -> None:
    rows = parse(PAGES)

    assert [r.number for r in rows] == [1, 2, 3]
    assert rows[0] == FundedProject(
        number=1,
        text="Nahwärme Hausen GmbH Nahwärmenetz Hausen",
        post_code="91353",
        town="Hausen",
        land="Bayern",
        grant_eur=187827.43,
    )
    assert rows[1].text == "Lübbener Wohnungsbaugesellschaft mbH Wärmenetz Quartier Puschkinstraße"
    assert (rows[2].land, rows[2].grant_eur) == ("Baden-Württemberg", 1109969.56)


def test_without_anlage_2_there_is_nothing_to_read() -> None:
    assert parse(["Anlage 1", "Anlage 3"]) == []
