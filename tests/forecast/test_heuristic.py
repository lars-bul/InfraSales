from datetime import date

import pytest

from infrasales.forecast.features import FEATURES, History, features
from infrasales.forecast.heuristic import BIAS, WEIGHTS, Heuristic
from infrasales.forecast.scoring import sigmoid
from infrasales.projects.models import SignalKind, TenderKind
from tests.forecast.support import HEIDELBERG, ULM, construction, signal

AS_OF = date(2026, 1, 1)


def test_every_feature_has_a_weight() -> None:
    assert set(WEIGHTS) == set(FEATURES)
    assert Heuristic.default().features == FEATURES


def test_signals_that_precede_a_tender_raise_the_score() -> None:
    signals = [
        (HEIDELBERG.ags, signal(SignalKind.COUNCIL_DECISION, date(2025, 5, 1))),
        (HEIDELBERG.ags, signal(SignalKind.FUNDING_GRANTED, date(2025, 9, 1))),
    ]
    planning = [(HEIDELBERG.ags, construction(date(2025, 3, 1), kind=TenderKind.PLANNING))]
    history = History.of([HEIDELBERG, ULM], signals=signals, tenders=planning)
    rule = Heuristic.default()

    active = rule.score(features(history, HEIDELBERG.ags, AS_OF))
    quiet = rule.score(features(history, ULM.ags, AS_OF))

    assert 0 < quiet < active < 1


def test_its_reasons_name_what_sets_a_place_apart() -> None:
    signals = [(HEIDELBERG.ags, signal(SignalKind.FUNDING_GRANTED, date(2025, 9, 1)))]
    history = History.of([HEIDELBERG, ULM], signals=signals)
    rows = [features(history, place.ags, AS_OF) for place in (HEIDELBERG, ULM)]
    baseline = [sum(column) / 2 for column in zip(*rows, strict=True)]

    reasons = Heuristic.default().reasons(rows[0], baseline)

    assert reasons[0].feature == "recent_funding_granted"


def test_stored_parameters_give_the_same_heuristic_back() -> None:
    rule = Heuristic.default()

    assert Heuristic.from_parameters(FEATURES, rule.parameters()) == rule


def test_stored_parameters_lacking_weights_or_bias_fall_back() -> None:
    stored = Heuristic.from_parameters(["a", "b"], {"weights": {"a": 2, "b": "x"}, "bias": True})

    assert stored == Heuristic((2.0, 0.0), BIAS, ("a", "b"))
    assert Heuristic.from_parameters(["a"], {}).weights == (0.0,)


def test_its_score_is_no_probability() -> None:
    assert Heuristic.default().calibrated is False
    assert Heuristic.default().score([0.0] * len(FEATURES)) == pytest.approx(sigmoid(BIAS))
