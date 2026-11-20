"""Field types for settings read from the environment."""

from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, HttpUrl
from pydantic_settings import NoDecode


def _comma_separated(value: object) -> object:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


CommaSeparated = Annotated[list[str], NoDecode, BeforeValidator(_comma_separated)]


def _exact_url(value: str) -> str:
    HttpUrl(value)
    return value


ExactUrl = Annotated[str, AfterValidator(_exact_url)]
