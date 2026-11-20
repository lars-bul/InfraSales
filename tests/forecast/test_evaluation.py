import pytest

from infrasales.forecast.evaluation import average_precision, brier, precision_at, roc_auc


def test_roc_auc_is_one_for_a_perfect_ranking_and_a_half_for_ties() -> None:
    assert roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert roc_auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0
    assert roc_auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5


def test_roc_auc_counts_a_tie_between_a_positive_and_a_negative_half() -> None:
    assert roc_auc([0, 1, 0], [0.1, 0.5, 0.5]) == 0.75


def test_roc_auc_needs_both_classes() -> None:
    assert roc_auc([1, 1], [0.1, 0.2]) is None
    assert roc_auc([], []) is None


def test_average_precision_rewards_positives_at_the_top() -> None:
    assert average_precision([1, 0, 1], [0.9, 0.8, 0.7]) == pytest.approx((1 + 2 / 3) / 2)
    assert average_precision([0, 1], [0.9, 0.1]) == 0.5
    assert average_precision([0, 0], [0.9, 0.1]) is None


def test_precision_at_k_is_the_share_of_positives_among_the_best_scored() -> None:
    labels, scores = [1, 0, 1, 0, 0], [0.9, 0.8, 0.7, 0.2, 0.1]

    assert precision_at(labels, scores, 2) == 0.5
    assert precision_at(labels, scores, 3) == pytest.approx(2 / 3)
    assert precision_at(labels, scores, 50) == 0.4  # fewer rows than k: all of them
    assert precision_at([], [], 2) is None
    assert precision_at(labels, scores, 0) is None


def test_brier_is_the_mean_squared_gap() -> None:
    assert brier([1, 0], [0.8, 0.4]) == pytest.approx((0.04 + 0.16) / 2)
    assert brier([], []) is None
