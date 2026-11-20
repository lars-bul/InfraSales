"""The AI settings as stored, and as admins read and change them (ADR 05)."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from infrasales.ai.providers import Provider
from infrasales.ai.settings import ChatProvider

_MODEL_ID = r"[\w.:/@~+-]{1,200}"
MODEL_ID = re.compile(_MODEL_ID)
_API_KEY = re.compile(r"[\x21-\x7e]{8,512}")

type ModelId = Annotated[str, Field(pattern=f"^{_MODEL_ID}$")]


class ChatModel(BaseModel):
    provider: ChatProvider
    model: str = Field(default="", pattern=f"^({_MODEL_ID})?$")

    @model_validator(mode="after")
    def _a_service_needs_a_model(self) -> Self:
        if self.provider != "mock" and not self.model:
            msg = "a service needs a model"
            raise ValueError(msg)
        return self


class EmbeddingModel(BaseModel):
    provider: Provider
    model: ModelId


class Models(BaseModel):
    chat: ChatModel
    embedding: EmbeddingModel


class KeyState(StrEnum):
    SET = "set"
    UNSET = "unset"
    UNREADABLE = "unreadable"


class ConnectionRead(BaseModel):
    provider: Provider
    key: KeyState
    revision: int
    updated_at: datetime


class ModelsRead(Models):
    revision: int
    updated_at: datetime


class AiSettingsRead(BaseModel):
    connections: list[ConnectionRead]
    models: ModelsRead
    keys_storable: bool


class ConnectionWrite(BaseModel):
    api_key: SecretStr | None

    @field_validator("api_key")
    @classmethod
    def _one_token(cls, key: SecretStr | None) -> SecretStr | None:
        if key is not None and not _API_KEY.fullmatch(key.get_secret_value()):
            msg = "an API key is 8 to 512 visible ASCII characters"
            raise ValueError(msg)
        return key
