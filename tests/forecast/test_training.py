from datetime import date

import numpy as np
import pytest

from infrasales.forecast.features import FEATURES, History, add_months
from infrasales.forecast.training import (
    NotEnoughDataError,
    backtest,
    dataset,
    snapshot_days,
    train,
    without,
)
from infrasales.projects.models import SignalKind
from tests.forecast.support import HEIDELBERG, ULM, construction, signal, world


@pytest.fixture(scope="module")
def synthetic() -> History:
    return world()


def test_snapshots_stop_a_horizon_before_the_last_day_observed(synthetic: History) -> None:
    last = synthetic.last_day()
    assert last is not None

    days = snapshot_days(synthetic, 24)

    assert days[0] == date(2018, 1, 1)  # eight years before the last day, 2026-01-01
    assert add_months(days[-1], 24) <= last < add_months(days[-1], 27)
    assert snapshot_days(History.of([HEIDELBERG]), 24) == []


def test_snapshots_go_back_eight_years_at_most() -> None:
    signals = [
        (HEIDELBERG.ags, signal(SignalKind.JOB_POSTING, date(2005, 1, 1))),
        (HEIDELBERG.ags, signal(SignalKind.JOB_POSTING, date(2026, 1, 1))),
    ]

    days = snapshot_days(History.of([HEIDELBERG], signals=signals), 12)

    assert days[0] == date(2018, 1, 1)


def test_a_dataset_has_every_place_on_every_day_with_its_label() -> None:
    history = History.of([HEIDELBERG, ULM], tenders=[(ULM.ags, construction(date(2026, 5, 1)))])

    data = dataset(history, [date(2025, 1, 1), date(2026, 1, 1)], 12)

    assert data.x.shape == (4, len(FEATURES))
    assert [
        (row.ags, row.as_of.year, int(y)) for row, y in zip(data.rows, data.y, strict=True)
    ] == [
        (HEIDELBERG.ags, 2025, 0),
        (ULM.ags, 2025, 0),
        (HEIDELBERG.ags, 2026, 0),
        (ULM.ags, 2026, 1),
    ]
    assert data.positives == 1
    assert data.where([False, True, False, True]).positives == 1


def test_an_empty_dataset_keeps_its_width() -> None:
    assert dataset(History.of([HEIDELBERG]), [], 12).x.shape == (0, len(FEATURES))


def test_the_backtest_learns_what_precedes_a_tender(synthetic: History) -> None:
    result = backtest(synthetic, horizon_months=12)

    learned, rule = result.learned, result.heuristic
    assert isinstance(learned["roc_auc"], float)
    assert learned["roc_auc"] > 0.8
    assert isinstance(rule["roc_auc"], float)
    assert rule["roc_auc"] > 0.7  # the heuristic knows decisions and funding come first
    assert learned["brier"] is not None
    assert rule["brier"] is None  # a heuristic's score is no probability
    assert isinstance(learned["lead_months_median"], float)
    assert 0 < learned["lead_months_median"] <= 12
    assert result.as_json()["cut"] == result.cut.isoformat()


def test_the_backtest_never_trains_on_a_label_unknown_at_the_cut(synthetic: History) -> None:
    """Every training label was known by the cut: the horizon of its snapshot ended before it."""
    result = backtest(synthetic, horizon_months=12)
    days = snapshot_days(synthetic, 12)

    trained_on = [day for day in days if add_months(day, 12) <= result.cut]
    tested_on = [day for day in days if day >= result.cut]

    assert trained_on
    assert tested_on
    assert max(trained_on) < result.cut <= min(tested_on)


def test_too_few_tenders_are_a_hard_limit() -> None:
    history = History.of(
        [HEIDELBERG, ULM],
        signals=[(HEIDELBERG.ags, signal(SignalKind.JOB_POSTING, date(2026, 1, 1)))],
        tenders=[(ULM.ags, construction(date(2020, 5, 1)))],
    )

    with pytest.raises(NotEnoughDataError) as raised:
        backtest(history, horizon_months=12)
    with pytest.raises(NotEnoughDataError):
        train(history, horizon_months=12)

    assert raised.value.needed == 60
    assert raised.value.positives < 60


def test_a_cut_leaving_too_few_positives_to_train_on_is_a_hard_limit(synthetic: History) -> None:
    with pytest.raises(NotEnoughDataError):
        backtest(
            synthetic, horizon_months=12, min_positives=int(synthetic_positives(synthetic) / 2)
        )


def synthetic_positives(history: History) -> int:
    return dataset(history, snapshot_days(history, 12), 12).positives


def test_training_uses_every_known_label_and_tells_until_when(synthetic: History) -> None:
    model, until = train(synthetic, horizon_months=12)

    assert until == synthetic.last_day()
    assert model.features == FEATURES
    council = FEATURES.index("recent_council_decision")
    jobs = FEATURES.index("recent_job_posting")
    assert model.coef[council] > model.coef[jobs]
    assert np.isfinite(model.intercept)


def test_left_out_features_are_held_at_zero_on_both_sides() -> None:
    history = History.of([HEIDELBERG, ULM], tenders=[(ULM.ags, construction(date(2026, 5, 1)))])
    data = dataset(history, [date(2025, 1, 1)], 12)

    kept = without(data, [])
    dropped = without(data, ["log_population"])

    assert kept is data
    assert dropped.x[:, FEATURES.index("log_population")].tolist() == [0.0, 0.0]
    assert data.x[:, FEATURES.index("log_population")].tolist() != [0.0, 0.0]


def test_the_backtest_without_its_decisive_signals_ranks_worse(synthetic: History) -> None:
    full = backtest(synthetic, horizon_months=12)
    blind = backtest(
        synthetic, horizon_months=12, drop=["recent_council_decision", "recent_funding_granted"]
    )

    assert isinstance(full.learned["roc_auc"], float)
    assert isinstance(blind.learned["roc_auc"], float)
    assert blind.learned["roc_auc"] < full.learned["roc_auc"]
