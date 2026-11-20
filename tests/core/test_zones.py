import pytest
from pydantic import TypeAdapter, ValidationError

from infrasales.core.zones import TimeZoneName, known_timezone

ZONE: TypeAdapter[str] = TypeAdapter(TimeZoneName)


@pytest.mark.parametrize("name", ["Europe/Berlin", "UTC", "America/New_York"])
def test_a_known_time_zone_name_is_kept(name: str) -> None:
    assert known_timezone(name) == name
    assert ZONE.validate_python(name) == name


@pytest.mark.parametrize("name", ["Mars/Olympus", "", "../etc/passwd", "europe berlin"])
def test_an_unknown_time_zone_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="unknown timezone"):
        known_timezone(name)
    with pytest.raises(ValidationError, match="unknown timezone"):
        ZONE.validate_python(name)
