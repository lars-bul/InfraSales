"""The services the models run on, and where each is reached (ADR 05)."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import SecretStr


class Provider(StrEnum):
    OPENROUTER = "openrouter"


BASE_URLS = {
    Provider.OPENROUTER: "https://openrouter.ai/api/v1",
}


@dataclass(frozen=True, slots=True)
class Connection:
    provider: Provider
    api_key: SecretStr

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.provider]
