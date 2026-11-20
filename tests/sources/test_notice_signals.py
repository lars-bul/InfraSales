from dataclasses import replace
from datetime import date

import pytest

from infrasales.projects.models import SignalKind, TenderKind, TenderStatus
from infrasales.sources.heat import Relevance
from infrasales.sources.notice_signals import kind_of, signals_of
from infrasales.sources.records import LotRecord


@pytest.mark.parametrize(
    ("title", "kind"),
    [
        (
            "Erstellung einer kommunalen Wärmeplanung für die Stadt Weinheim",
            SignalKind.HEAT_PLAN_STARTED,
        ),
        ("Transformationsplan Fernwärme Nord (BEW Modul 1)", SignalKind.FEASIBILITY_STUDY),
        ("Machbarkeitsstudie Nahwärmenetz Ortskern", SignalKind.FEASIBILITY_STUDY),
        ("Errichtung einer Großwärmepumpe am Klärwerk", SignalKind.HEAT_SOURCE_PROJECT),
        ("Neubau Grundschule", None),
    ],
)
def test_a_title_names_the_early_step_it_commissions(title: str, kind: SignalKind | None) -> None:
    assert kind_of(title) is kind


def test_a_notice_gives_one_signal_per_kind_dated_by_its_publication() -> None:
    lot = LotRecord(
        source="doe",
        notice_id="n-1",
        notice_type="cn-standard",
        procedure_ref="p",
        lot="LOT-0001",
        title="Kommunale Wärmeplanung Musterstadt",
        kind=TenderKind.PLANNING,
        status=TenderStatus.PUBLISHED,
        published_on=date(2024, 2, 1),
        relevance=Relevance(heat_network=False, reason="no-network"),
        place_post_code="69117",
    )

    (signal,) = signals_of([lot, replace(lot, lot="LOT-0002"), replace(lot, title="Neubau Schule")])

    assert (signal.kind, signal.ref, signal.available_on, signal.post_code) == (
        SignalKind.HEAT_PLAN_STARTED,
        "doe:n-1:heat_plan_started",
        date(2024, 2, 1),
        "69117",
    )
