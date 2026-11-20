"""Dates as documents and feeds write them."""

from datetime import UTC, datetime


def parse_date(value: object) -> datetime | None:
    """An ISO 8601 date or time as an aware datetime (UTC when it names no offset), else None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
