from pathlib import Path

from infrasales.sources.places import PostCodeArea, Resolver, normalized, read_streets
from tests.sources.support import streets

MUNICIPALITIES = [
    ("08221000", "Heidelberg, Stadt"),
    ("08226095", "Walldorf, Stadt"),
    ("08226099", "Wiesloch, Stadt"),
    ("06433012", "Walldorf, Stadt"),  # Mörfelden-Walldorf's part in Hesse, for the name's sake
]
AREAS = [
    PostCodeArea("69117", "Heidelberg", "08221000", 300),
    PostCodeArea("69190", "Walldorf", "08226095", 120),
    PostCodeArea("69190", "Wiesloch", "08226099", 10),
]


def resolver() -> Resolver:
    return Resolver.of(MUNICIPALITIES, AREAS)


def test_names_are_compared_without_brackets_kind_or_case() -> None:
    assert normalized("Neunkirchen (Baden)") == "neunkirchen"
    assert normalized("Flensburg, Stadt") == "flensburg"
    assert normalized("Große Kreisstadt Weißenburg") == "weissenburg"


def test_a_post_code_resolves_to_the_municipality_its_town_names_else_most_streets() -> None:
    places = resolver()

    assert places.resolve("69117", None) == "08221000"
    assert places.resolve("69190", "Wiesloch") == "08226099"
    assert places.resolve("69190", "Irgendwo") == "08226095"
    assert places.resolve("69190 ", "Walldorf") == "08226095"


def test_without_a_known_post_code_a_unique_name_in_the_land_resolves() -> None:
    places = resolver()

    assert places.resolve(None, "Heidelberg") == "08221000"
    assert places.resolve(None, "Walldorf") is None  # one in each Land
    assert places.resolve(None, "Walldorf", "DE128") == "08226095"
    assert places.resolve("99999", None) is None


def test_streets_are_summed_per_post_code_locality_and_municipality(tmp_path: Path) -> None:
    path = streets(
        tmp_path / "streets.csv",
        [
            ("Hauptstr.", "69117", "Heidelberg", "08221000"),
            ("Bergstr.", "69117", "Heidelberg", "08221000"),
            ("Weg", "69190", "Walldorf", "08226095"),
            ("Kaputt", "69190", "Walldorf", "0822"),
        ],
    )

    assert list(read_streets(path)) == [
        PostCodeArea("69117", "Heidelberg", "08221000", 2),
        PostCodeArea("69190", "Walldorf", "08226095", 1),
    ]
