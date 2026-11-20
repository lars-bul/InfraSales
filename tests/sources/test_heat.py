import pytest

from infrasales.projects.models import TenderKind
from infrasales.sources.heat import kind_of, relevance


@pytest.mark.parametrize(
    ("main", "codes", "titles", "descriptions", "network", "reason"),
    [
        (["45232140"], [], ["Tiefbau"], [], True, "code:45232140"),
        (["45000000"], [], ["Neubau Wärmenetz Weststadt"], [], True, "words:title"),
        (
            ["45231000"],
            [],
            ["Leitungsbau BA 3"],
            ["Verlegung Fernwärmeleitung DN 200"],
            True,
            "words:description+code",
        ),
        (["09323000"], [], ["Fernwärme"], [], False, "heat-supply"),
        (["65000000"], [], ["Lieferung von Fernwärme 2026"], [], False, "heat-supply"),
        (["45000000"], [], ["Fernwärmeanschluss Rathaus"], [], False, "connection"),
        (["45214000"], ["45232142"], ["Neubau Grundschule"], [], False, "secondary-code"),
        (["45232141"], [], ["Heizungsanlagen"], [], False, "no-network"),
        (["45231300"], [], ["Erneuerung Wasserleitung Hauptstraße"], [], False, "pipeline"),
    ],
)
def test_a_notice_concerns_a_heat_network_by_its_main_code_or_its_own_words(  # noqa: PLR0913, PLR0917
    main: list[str],
    codes: list[str],
    titles: list[str],
    descriptions: list[str],
    network: bool,  # noqa: FBT001
    reason: str,
) -> None:
    decided = relevance(main, codes, titles, descriptions)

    assert (decided.heat_network, decided.reason) == (network, reason)


@pytest.mark.parametrize(
    ("nature", "codes", "kind"),
    [
        ("works", ["71000000"], TenderKind.CONSTRUCTION),
        ("supplies", [], TenderKind.SUPPLY),
        ("services", ["71320000"], TenderKind.PLANNING),
        ("services", ["50000000"], TenderKind.SERVICE),
        (None, ["45232140"], TenderKind.CONSTRUCTION),
        (None, ["71322000"], TenderKind.PLANNING),
        (None, ["44163000"], TenderKind.SUPPLY),
        (None, ["79000000"], TenderKind.SERVICE),
    ],
)
def test_the_kind_of_contract_comes_from_its_nature_else_its_codes(
    nature: str | None, codes: list[str], kind: TenderKind
) -> None:
    assert kind_of(nature, codes) is kind
