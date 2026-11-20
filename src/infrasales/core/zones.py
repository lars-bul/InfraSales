"""IANA time zones, by the names clients send (e.g. "Europe/Berlin")."""

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, Field


def known_timezone(name: str) -> str:
    """`name` if it names a time zone the system knows, else a ValueError (a 422 in the API)."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        msg = f"unknown timezone {name!r}"
        raise ValueError(msg) from error
    return name


TimeZoneName = Annotated[str, AfterValidator(known_timezone), Field(examples=["Europe/Berlin"])]
