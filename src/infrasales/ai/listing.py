"""The models each service offers, for the Settings page to pick from (ADR 05)."""

from enum import StrEnum

import httpx2
from pydantic import BaseModel, SecretStr

from infrasales.ai.providers import BASE_URLS, Provider
from infrasales.ai.schemas import MODEL_ID


class Purpose(StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"


class ModelOption(BaseModel):
    id: str
    name: str


TIMEOUT_SECONDS = 15
_URLS = {
    (Provider.OPENROUTER, Purpose.CHAT): f"{BASE_URLS[Provider.OPENROUTER]}/models",
    (Provider.OPENROUTER, Purpose.EMBEDDING): f"{BASE_URLS[Provider.OPENROUTER]}/embeddings/models",
}


class KeyRefusedError(Exception):
    """The service lists its models for a valid key only."""


class ModelsUnavailableError(Exception):
    """The service did not list its models."""


class _Listed(BaseModel):
    id: str
    name: str | None = None


class _Listing(BaseModel):
    data: list[_Listed]


async def available(
    provider: Provider,
    purpose: Purpose,
    api_key: SecretStr | None,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> list[ModelOption]:
    """The models `provider` offers for `purpose`, by id; those a key may use, given one."""
    headers = {"Authorization": f"Bearer {api_key.get_secret_value()}"} if api_key else {}
    async with httpx2.AsyncClient(
        transport=transport, timeout=TIMEOUT_SECONDS, headers=headers
    ) as client:
        try:
            response = await client.get(_URLS[provider, purpose])
            if response.status_code in {401, 403}:
                raise KeyRefusedError
            response.raise_for_status()
            listed = _Listing.model_validate_json(response.content).data
        except (httpx2.HTTPError, ValueError) as error:
            raise ModelsUnavailableError(type(error).__name__) from error
    options = {
        model.id: ModelOption(id=model.id, name=model.name or model.id)
        for model in listed
        if MODEL_ID.fullmatch(model.id)
    }
    return [options[key] for key in sorted(options)]
