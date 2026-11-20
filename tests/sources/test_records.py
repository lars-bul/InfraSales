from datetime import date

import pytest

from infrasales.projects.models import TenderKind, TenderStatus
from infrasales.sources.heat import Relevance
from infrasales.sources.records import LotRecord, months, status_of


def a_lot(procedure: str | None, lot: str | None) -> LotRecord:
    return LotRecord(
        source="ted",
        notice_id="123-2024",
        notice_type="cn-standard",
        procedure_ref=procedure,
        lot=lot,
        title="Wärmenetz",
        kind=TenderKind.CONSTRUCTION,
        status=TenderStatus.PUBLISHED,
        published_on=date(2024, 1, 1),
        relevance=Relevance(heat_network=True, reason="words:title"),
    )


def test_a_lot_is_found_by_its_procedure_and_lot_else_its_notice() -> None:
    assert a_lot("abc", "LOT-0002").key == "proc:abc:LOT-0002"
    assert a_lot("abc", None).key == "proc:abc:LOT-0000"
    assert a_lot(None, None).key == "ted:123-2024:LOT-0000"


@pytest.mark.parametrize(
    ("notice_type", "awarded", "status"),
    [
        ("pin-only", False, TenderStatus.PLANNED),
        ("cn-standard", False, TenderStatus.PUBLISHED),
        ("can-standard", True, TenderStatus.AWARDED),
        ("can-standard", False, TenderStatus.CANCELLED),
        ("veat", True, TenderStatus.AWARDED),
        ("corr", True, None),
        ("can-modif", True, TenderStatus.AWARDED),
    ],
)
def test_a_notice_type_gives_its_lots_a_status(
    notice_type: str,
    awarded: bool,  # noqa: FBT001
    status: TenderStatus | None,
) -> None:
    assert status_of(notice_type, awarded=awarded) is status


def test_durations_are_counted_in_months() -> None:
    assert months(2, "YEAR") == 24
    assert months(61, "DAY") == pytest.approx(2.0, abs=0.01)
    assert months(3, "MONTH") == 3
    assert months(3, "DECADE") is None
    assert months(None, "MONTH") is None
