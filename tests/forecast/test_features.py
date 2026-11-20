import math
from datetime import date

import pytest

from infrasales.forecast.features import (
    FEATURES,
    History,
    Place,
    add_months,
    features,
    label,
    months_between,
    next_tender,
    quarters,
)
from infrasales.projects.models import (
    MetricKind,
    SignalKind,
    TenderKind,
    TenderOrigin,
    TenderStatus,
)
from tests.forecast.support import HEIDELBERG, ULM, WALDDORF, construction, metric, signal

AS_OF = date(2026, 1, 1)


def feature(history: History, name: str, ags: str = HEIDELBERG.ags, as_of: date = AS_OF) -> float:
    return dict(zip(FEATURES, features(history, ags, as_of), strict=True))[name]


def test_there_is_a_value_for_every_feature_name() -> None:
    history = History.of([HEIDELBERG])

    assert len(features(history, HEIDELBERG.ags, AS_OF)) == len(FEATURES) == len(set(FEATURES))


def test_a_signal_counts_only_from_the_day_it_became_available() -> None:
    council = signal(SignalKind.COUNCIL_DECISION, date(2026, 3, 1), occurred_on=date(2025, 12, 1))
    history = History.of([HEIDELBERG], signals=[(HEIDELBERG.ags, council)])

    before = feature(history, "recent_council_decision", as_of=date(2026, 2, 28))
    on_the_day = feature(history, "recent_council_decision", as_of=date(2026, 3, 1))

    assert (before, on_the_day) == (0.0, math.log1p(1))  # decided earlier, but not yet known


def test_the_future_never_changes_a_past_days_features() -> None:
    past = [(HEIDELBERG.ags, signal(SignalKind.FUNDING_GRANTED, date(2025, 6, 1)))]
    future = [
        (HEIDELBERG.ags, signal(SignalKind.COUNCIL_DECISION, date(2026, 2, 1))),
        (HEIDELBERG.ags, signal(SignalKind.HEAT_PLAN_ADOPTED, date(2026, 5, 1))),
    ]
    later_tender = [(HEIDELBERG.ags, construction(date(2026, 4, 1)))]
    later_metric = [
        (HEIDELBERG.ags, metric(MetricKind.DISTRICT_HEATING_SHARE, AS_OF.replace(day=2), 0.3))
    ]

    known = History.of([HEIDELBERG], signals=past)
    with_future = History.of(
        [HEIDELBERG], signals=past + future, tenders=later_tender, metrics=later_metric
    )

    assert features(with_future, HEIDELBERG.ags, AS_OF) == features(known, HEIDELBERG.ags, AS_OF)


def test_signals_older_than_the_recent_months_no_longer_count() -> None:
    old = signal(SignalKind.FUNDING_GRANTED, date(2023, 12, 31))
    fresh = signal(SignalKind.FUNDING_GRANTED, date(2024, 1, 2))
    history = History.of([HEIDELBERG], signals=[(HEIDELBERG.ags, old), (HEIDELBERG.ags, fresh)])

    assert feature(history, "recent_funding_granted") == math.log1p(1)


def test_size_density_and_the_heat_plan_deadline_of_a_large_and_a_small_place() -> None:
    history = History.of([HEIDELBERG, WALDDORF])

    large = [feature(history, n) for n in ("large_city", "log_population", "log_density")]
    small_deadline = feature(history, "plan_deadline_passed", WALDDORF.ags, date(2027, 1, 1))
    large_deadline = feature(history, "plan_deadline_passed", HEIDELBERG.ags, date(2027, 1, 1))

    assert large == [1.0, math.log1p(162_000), math.log1p(162_000 / 108.8)]
    assert (large_deadline, small_deadline) == (1.0, 0.0)  # 30 June 2026 above 100,000 people


def test_a_place_without_population_or_area_has_neither_size_nor_density() -> None:
    history = History.of([Place("08000001", "Unbekannt")])

    assert [feature(history, n, "08000001") for n in ("log_population", "log_density")] == [0, 0]


def test_the_years_since_the_heat_plan_count_from_its_adoption_up_to_five() -> None:
    adopted = signal(SignalKind.HEAT_PLAN_ADOPTED, date(2024, 2, 1), occurred_on=date(2024, 1, 1))
    history = History.of([HEIDELBERG], signals=[(HEIDELBERG.ags, adopted)])

    two_years = feature(history, "years_since_heat_plan", as_of=date(2026, 1, 1))
    later = feature(history, "years_since_heat_plan", as_of=date(2035, 1, 1))

    assert two_years == pytest.approx(2.0, abs=0.01)
    assert later == 5.0
    assert feature(history, "heat_plan_adopted") == 1.0


def test_a_gas_concession_counts_when_it_ends_within_three_years() -> None:
    ends = signal(SignalKind.GAS_CONCESSION_ENDS, date(2025, 1, 1), occurred_on=date(2028, 6, 30))
    history = History.of([HEIDELBERG], signals=[(HEIDELBERG.ags, ends)])

    soon = feature(history, "gas_concession_ends_soon", as_of=date(2026, 1, 1))
    too_early = feature(history, "gas_concession_ends_soon", as_of=date(2025, 6, 1))
    over = feature(history, "gas_concession_ends_soon", as_of=date(2028, 7, 1))

    assert (soon, too_early, over) == (1.0, 0.0, 0.0)


def test_only_notices_that_came_out_count_as_tendered() -> None:
    tenders = [
        construction(date(2025, 3, 1)),
        construction(date(2025, 4, 1), origin=TenderOrigin.PRIVATE_REQUEST),
        construction(date(2025, 5, 1), origin=TenderOrigin.PREVIEW),  # announced only
        construction(date(2025, 6, 1), status=TenderStatus.PLANNED),
        construction(date(2025, 7, 1), kind=TenderKind.PLANNING),
    ]
    history = History.of([HEIDELBERG], tenders=[(HEIDELBERG.ags, t) for t in tenders])

    assert feature(history, "recent_construction_tenders") == math.log1p(2)
    assert feature(history, "construction_tenders_before") == math.log1p(2)
    assert feature(history, "recent_planning_tenders") == math.log1p(1)


def test_a_planned_construction_tender_in_a_preview_is_a_feature_of_its_own() -> None:
    preview = construction(
        date(2026, 9, 1),
        available_on=date(2025, 11, 1),
        origin=TenderOrigin.PREVIEW,
        status=TenderStatus.PLANNED,
    )
    history = History.of([HEIDELBERG], tenders=[(HEIDELBERG.ags, preview)])

    assert feature(history, "construction_planned") == 1.0
    assert feature(history, "construction_planned", as_of=date(2025, 10, 31)) == 0.0


def test_a_framework_agreement_running_out_soon_is_a_feature() -> None:
    framework = construction(date(2022, 1, 1), framework=True, contract_end_on=date(2027, 6, 30))
    history = History.of([HEIDELBERG], tenders=[(HEIDELBERG.ags, framework)])

    assert feature(history, "framework_ends_soon") == 1.0
    assert feature(history, "framework_ends_soon", as_of=date(2025, 1, 1)) == 0.0


def test_a_metric_is_its_latest_value_available_on_the_day() -> None:
    metrics = [
        metric(MetricKind.DISTRICT_HEATING_SHARE, date(2014, 5, 1), 0.08),
        metric(MetricKind.DISTRICT_HEATING_SHARE, date(2024, 6, 1), 0.12),
        metric(MetricKind.GAS_HEATING_SHARE, date(2024, 6, 1), 0.55),
    ]
    history = History.of([HEIDELBERG], metrics=[(HEIDELBERG.ags, m) for m in metrics])

    assert feature(history, "district_heating_share", as_of=date(2020, 1, 1)) == 0.08
    assert feature(history, "district_heating_share") == 0.12
    assert feature(history, "gas_heating_share") == 0.55


def test_the_label_is_a_construction_tender_published_within_the_horizon() -> None:
    tenders = [
        (HEIDELBERG.ags, construction(date(2027, 1, 1))),
        (ULM.ags, construction(date(2028, 1, 2))),
        (WALDDORF.ags, construction(AS_OF)),  # on the day: already known, not a forecast
    ]
    history = History.of([HEIDELBERG, ULM, WALDDORF], tenders=tenders)

    labels = [label(history, place.ags, AS_OF, 24) for place in (HEIDELBERG, ULM, WALDDORF)]

    assert labels == [True, False, False]
    assert next_tender(history, ULM.ags, AS_OF) == date(2028, 1, 2)
    assert next_tender(history, WALDDORF.ags, AS_OF) is None


def test_a_history_keeps_only_known_places_and_its_facts_in_order() -> None:
    history = History.of(
        [HEIDELBERG],
        signals=[
            (HEIDELBERG.ags, signal(SignalKind.JOB_POSTING, date(2025, 5, 1))),
            (HEIDELBERG.ags, signal(SignalKind.JOB_POSTING, date(2024, 5, 1))),
            ("09162000", signal(SignalKind.JOB_POSTING, date(2026, 5, 1))),
        ],
    )

    days = [s.available_on for s in history.signals[HEIDELBERG.ags]]

    assert days == [date(2024, 5, 1), date(2025, 5, 1)]
    assert "09162000" not in history.signals
    assert history.last_day() == date(2025, 5, 1)
    assert History.of([HEIDELBERG]).last_day() is None


@pytest.mark.parametrize(
    ("day", "months", "moved"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2026, 3, 31), -1, date(2026, 2, 28)),
        (date(2026, 11, 15), 3, date(2027, 2, 15)),
        (date(2026, 1, 1), -24, date(2024, 1, 1)),
    ],
)
def test_months_are_added_at_the_end_of_a_shorter_month(
    day: date, months: int, moved: date
) -> None:
    assert add_months(day, months) == moved


def test_months_between_count_whole_months_and_the_days_as_a_fraction() -> None:
    assert months_between(date(2026, 1, 1), date(2027, 1, 1)) == 12
    assert months_between(date(2026, 1, 1), date(2026, 1, 16)) == pytest.approx(15 / 31)
    assert months_between(date(2027, 1, 1), date(2026, 1, 1)) == -12


def test_quarters_start_at_the_first_days_quarter_and_include_the_last_day() -> None:
    assert quarters(date(2025, 5, 17), date(2026, 1, 1)) == [
        date(2025, 4, 1),
        date(2025, 7, 1),
        date(2025, 10, 1),
        date(2026, 1, 1),
    ]
    assert quarters(date(2026, 2, 1), date(2025, 1, 1)) == []
