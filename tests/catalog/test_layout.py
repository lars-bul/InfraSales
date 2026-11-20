import uuid
from datetime import UTC, datetime, timedelta, timezone

from infrasales.catalog.layout import raw_name, run_folder, version_folder


def test_a_run_folder_is_its_scheduled_time_in_utc_without_colons() -> None:
    berlin = timezone(timedelta(hours=2))

    assert (
        run_folder(datetime(2026, 10, 16, 8, 0, 0, 999_999, tzinfo=berlin)) == "2026-10-16T060000Z"
    )
    assert run_folder(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2026-01-02T030405Z"


def test_a_version_folder_is_below_its_run_and_feed() -> None:
    version = uuid.UUID("0199f0c2-0000-7000-8000-000000000000")

    assert version_folder("2026-10-16T060000Z", "tiefbau-aktuell", version) == (
        "2026-10-16T060000Z/tiefbau-aktuell/0199f0c2-0000-7000-8000-000000000000"
    )


def test_the_raw_file_is_named_by_media_type() -> None:
    assert [raw_name(t) for t in ("text/html", "application/pdf", "application/json")] == [
        "raw.html",
        "raw.pdf",
        "raw.json",
    ]
    assert raw_name("image/png") == "raw.bin"
