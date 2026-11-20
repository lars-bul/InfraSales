import math

import pytest

from infrasales.forecast.scoring import Reason, explain, mean_vector, sigmoid


def test_sigmoid_is_the_logistic_function_without_overflow() -> None:
    assert sigmoid(0) == 0.5
    assert sigmoid(2) == pytest.approx(1 / (1 + math.exp(-2)))
    assert sigmoid(-2) == pytest.approx(1 - sigmoid(2))
    assert sigmoid(-1000) == 0.0
    assert sigmoid(1000) == 1.0


def test_reasons_are_the_features_lifting_the_score_most_above_the_baseline() -> None:
    names = ["population", "council", "funding", "jobs"]
    weights = [0.5, 1.4, 1.4, -0.2]

    reasons = explain(names, weights, [10.0, 1.0, 0.0, 3.0], [10.0, 0.1, 0.2, 1.0], top=3)

    assert reasons == [Reason("council", 1.0, pytest.approx(1.26))]  # pyright: ignore[reportArgumentType]


def test_at_most_the_top_reasons_are_given_strongest_first() -> None:
    reasons = explain(["a", "b", "c", "d"], [1, 2, 3, 4], [1, 1, 1, 1], [0, 0, 0, 0], top=2)

    assert [reason.feature for reason in reasons] == ["d", "c"]


def test_a_reason_rounds_for_json() -> None:
    assert Reason("council", 0.693147, 0.970406).as_json() == {
        "feature": "council",
        "value": 0.6931,
        "effect": 0.9704,
    }


def test_the_baseline_is_the_column_mean_and_zeros_without_rows() -> None:
    assert mean_vector([[1.0, 2.0], [3.0, 6.0]], 2) == [2.0, 4.0]
    assert mean_vector([], 3) == [0.0, 0.0, 0.0]
