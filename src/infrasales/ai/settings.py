"""The chat model's settings (`LLM__*`) and the connections' keys, seeds for the Settings page."""

from typing import Literal, Self

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from infrasales.ai.providers import Provider

type ChatProvider = Literal["mock"] | Provider


class LLMSettings(BaseModel):
    provider: ChatProvider = "mock"
    model: str = ""
    reply: str = "Hello world"
    max_wait_seconds: float = Field(default=120, ge=0)
    trace_content: bool = False

    @model_validator(mode="after")
    def _a_service_needs_a_model(self) -> Self:
        if self.provider != "mock" and not self.model:
            msg = "LLM__PROVIDER needs LLM__MODEL"
            raise ValueError(msg)
        return self


class ConnectionSettings(BaseModel):
    api_key: SecretStr | None = None

    @field_validator("api_key")
    @classmethod
    def _blank_is_unset(cls, key: SecretStr | None) -> SecretStr | None:
        return key if key and key.get_secret_value().strip() else None
