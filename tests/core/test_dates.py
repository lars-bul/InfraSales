from datetime import UTC, datetime, timedelta, timezone

import pytest

from infrasales.core.dates import parse_date


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "2026-10-16T08:30:00+02:00",
            datetime(2026, 10, 16, 8, 30, tzinfo=timezone(timedelta(hours=2))),
        ),
        (" 2026-10-16 ", datetime(2026, 10, 16, tzinfo=UTC)),  # no offset: UTC
        ("16 October 2026", None),
        ("", None),
        (None, None),
        (20261016, None),
    ],
)
def test_iso_dates_are_read_anything_else_is_none(given: object, expected: datetime | None) -> None:
    assert parse_date(given) == expected
