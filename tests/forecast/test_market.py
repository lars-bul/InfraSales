from infrasales.forecast.market import PastTender, describe, profile


def past(buyer: str, ags: str, **values: object) -> PastTender:
    base: dict[str, object] = {
        "procedure": "open",
        "lots": 1,
        "framework": False,
        "price_only": True,
        "duration_months": 12.0,
        "value_eur": 800_000,
        "offers": 3,
        "sme_suitable": None,
    }
    return PastTender(buyer=buyer, ags=ags, **{**base, **values})  # pyright: ignore[reportArgumentType]


TENDERS = [
    past("stadtwerke heidelberg", "08221000", offers=5, lots=3),
    past("stadtwerke heidelberg", "08221000", procedure="neg-w-call", offers=7),
    past("stadtwerke heidelberg", "08221000", price_only=False, offers=None),
    past("stadt ulm", "08421000", framework=True, value_eur=2_000_000),
    past("gemeinde walldorf", "08226095"),
    past("stadt münchen", "09162000", procedure="restricted"),
]


def test_a_buyer_with_enough_tenders_speaks_for_itself() -> None:
    found = profile(TENDERS, buyer="stadtwerke heidelberg", ags="08221000")

    assert (found.basis, found.tenders, found.procedure) == ("buyer", 3, "open")
    assert (found.procedure_share, found.lots_median, found.offers_median, found.offers_known) == (
        0.667,
        1.0,
        6.0,
        2,
    )
    assert found.price_only_share == 0.667


def test_a_buyer_with_too_few_is_described_by_its_land_then_by_all() -> None:
    assert profile(TENDERS, buyer="gemeinde walldorf", ags="08226095").basis == "land"
    assert profile(TENDERS, buyer=None, ags="16051000").basis == "all"


def test_a_profile_reads_as_json_and_describes_an_empty_group() -> None:
    empty = describe("all", [])

    assert empty.as_json()["tenders"] == 0
    assert (empty.procedure, empty.framework_share, empty.offers_median) == (None, 0.0, None)
