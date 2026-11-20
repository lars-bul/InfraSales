import random
from datetime import date

import pytest

from infrasales.forecast.features import add_months
from infrasales.forecast.winners import (
    UNKNOWN_DISTANCE_KM,
    Award,
    Firm,
    Market,
    WinModel,
    backtest,
    chance,
    choices,
    distance_km,
    features,
    fit,
)

HEIDELBERG = (49.40768, 8.69079)
ULM = (48.39841, 9.99155)


def synthetic_market(seed: int = 5, tenders: int = 400) -> Market:
    """Firms spread over a region; the nearest firm, or the buyer's incumbent, usually wins."""
    rng = random.Random(seed)  # noqa: S311  # test data
    firms = {f"firm {i}": (48 + rng.random() * 2, 8 + rng.random() * 3) for i in range(40)}
    buyers = [f"buyer {i}" for i in range(30)]
    incumbent: dict[str, str] = {}
    awards: list[Award] = []
    day = date(2018, 1, 1)
    for t in range(tenders):
        day = add_months(date(2018, 1, 1), t // 5)
        place = (48 + rng.random() * 2, 8 + rng.random() * 3)
        buyer = rng.choice(buyers)
        nearest = min(firms, key=lambda f: distance_km(firms[f], place))
        if buyer in incumbent and rng.random() < 0.4:
            winner = incumbent[buyer]
        elif rng.random() < 0.7:
            winner = nearest
        else:
            winner = rng.choice(list(firms))
        incumbent[buyer] = winner
        awards.append(
            Award(
                f"t{t}", day, buyer, "08", place, winner, firms[winner], large=winner.endswith("1")
            )
        )
    return Market.of(awards)


@pytest.fixture(scope="module")
def market() -> Market:
    return synthetic_market()


def test_distance_is_the_great_circle_and_unknown_places_are_far() -> None:
    assert distance_km(HEIDELBERG, ULM) == pytest.approx(147, abs=2)
    assert distance_km(None, ULM) == UNKNOWN_DISTANCE_KM


def test_a_firms_features_count_its_earlier_wins_with_the_buyer_and_in_the_land() -> None:
    win = Award("t0", date(2020, 1, 1), "buyer", "08", HEIDELBERG, "firm", HEIDELBERG, large=False)

    x = features(Firm("firm", HEIDELBERG, large=True, wins=[win, win]), "buyer", "08", HEIDELBERG)

    assert x[0] == 0.0  # no distance
    assert x[1:] == pytest.approx([1.0986, 1.0986, 1.0986, 1.0], abs=1e-4)


def test_the_market_of_a_day_holds_the_firms_that_won_within_the_years_before(
    market: Market,
) -> None:
    first_day = market.awards[0].day

    assert market.firms(first_day) == set()
    assert len(market.firms(date(2022, 1, 1))) > 10
    assert all(a.day < date(2019, 1, 1) for a in market.before(date(2019, 1, 1)))


def test_the_model_learns_that_near_firms_and_incumbents_win(market: Market) -> None:
    model = fit(choices(market, market.awards))

    distance, buyer_wins = model.coef[0], model.coef[1]
    assert distance < -0.5
    assert buyer_wins > 0.3
    assert WinModel.from_parameters(model.parameters()) == model


def test_the_backtest_beats_a_model_knowing_only_distance_and_chance(market: Market) -> None:
    result = backtest(market, date(2023, 1, 1))

    assert result.trained > 100
    assert result.tested > 50
    assert result.log_likelihood > result.log_likelihood_uniform
    assert result.log_likelihood >= result.log_likelihood_distance - 0.05
    assert result.top5 > result.top1 > 1 / result.mean_firms
    assert result.as_json()["cut"] == "2023-01-01"
    with pytest.raises(ValueError, match="to test on"):
        backtest(market, date(2040, 1, 1))


def test_a_near_contractor_has_a_better_chance_than_a_far_one(market: Market) -> None:
    model = fit(choices(market, market.awards))
    place = (49.0, 9.5)
    near = Firm("newcomer", place, large=False, wins=[])
    far = Firm("newcomer", (53.5, 10.0), large=False, wins=[])

    day = date(2024, 1, 1)
    near_chance = chance(model, market, near, buyer="buyer 1", land="08", place=place, day=day)
    far_chance = chance(model, market, far, buyer="buyer 1", land="08", place=place, day=day)

    assert 0 < far_chance < near_chance < 1
