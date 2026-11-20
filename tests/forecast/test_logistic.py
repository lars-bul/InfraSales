import numpy as np
import pytest

from infrasales.forecast.logistic import Logistic, fit


def separable(seed: int = 3, rows: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """Labels driven by the first feature, the second noise, the third constant."""
    rng = np.random.default_rng(seed)
    signal = rng.normal(size=rows)
    noise = rng.normal(size=rows)
    x = np.column_stack([signal * 5 + 10, noise, np.ones(rows)])
    y = (rng.random(rows) < 1 / (1 + np.exp(-(2 * signal - 1)))).astype(np.int_)
    return x, y


def test_it_learns_which_feature_drives_the_label() -> None:
    x, y = separable()

    model = fit(x, y, ["signal", "noise", "constant"])

    assert model.coef[0] > 1.0
    assert abs(model.coef[1]) < 0.3
    assert model.coef[2] == 0.0  # a constant feature has no effect, and no division by zero
    assert model.calibrated is True


def test_its_scores_are_probabilities_that_rank_by_the_driving_feature() -> None:
    x, y = separable()
    model = fit(x, y, ["signal", "noise", "constant"])

    low, high = model.score([5.0, 0.0, 1.0]), model.score([15.0, 0.0, 1.0])

    assert 0 < low < 0.5 < high < 1
    assert np.mean([model.score(row) for row in x.tolist()]) == pytest.approx(y.mean(), abs=0.02)


def test_more_regularisation_shrinks_the_coefficients() -> None:
    x, y = separable()

    loose = fit(x, y, ["signal", "noise", "constant"], l2=0.01)
    tight = fit(x, y, ["signal", "noise", "constant"], l2=500.0)

    assert abs(tight.coef[0]) < abs(loose.coef[0])


def test_its_reasons_are_per_unit_of_the_raw_feature() -> None:
    model = Logistic(("a", "b"), (0.0, 0.0), (2.0, 1.0), (1.0, 1.0), 0.0)

    reasons = model.reasons([4.0, 1.0], [0.0, 0.0])

    assert [(r.feature, r.effect) for r in reasons] == [("a", 2.0), ("b", 1.0)]


def test_stored_parameters_give_the_same_model_back() -> None:
    x, y = separable()
    model = fit(x, y, ["signal", "noise", "constant"])

    assert Logistic.from_parameters(model.features, model.parameters()) == model


@pytest.mark.parametrize(
    "parameters",
    [
        {"mean": [0.0], "scale": [1.0], "coef": [1.0]},
        {"mean": [0.0, 1.0], "scale": [1.0], "coef": [1.0], "intercept": 0.0},
        {"mean": "x", "scale": [1.0], "coef": [1.0], "intercept": 0.0},
    ],
)
def test_a_stored_model_missing_parameters_is_refused(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="stored model"):
        Logistic.from_parameters(["a"], parameters)  # pyright: ignore[reportArgumentType]


def test_rows_labels_and_features_must_fit() -> None:
    with pytest.raises(ValueError, match="do not fit"):
        fit(np.zeros((3, 2)), np.zeros(4, dtype=np.int_), ["a", "b"])
