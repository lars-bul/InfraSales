"""The chat model the agents use: the mock, or a service's model behind its rate limit."""

import httpx2
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from infrasales.ai.providers import Connection
from infrasales.ai.settings import LLMSettings


def mock_model(settings: LLMSettings) -> Model:
    return TestModel(custom_output_text=settings.reply)


def chat_client(
    settings: LLMSettings, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    from infrasales.ai.limits import RateLimitedTransport

    limited = RateLimitedTransport(
        transport or httpx2.AsyncHTTPTransport(), max_wait=settings.max_wait_seconds
    )
    return httpx2.AsyncClient(transport=limited)


def chat_model(model: str, connection: Connection, client: httpx2.AsyncClient) -> Model:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    provider = OpenAIProvider(
        base_url=connection.base_url,
        api_key=connection.api_key.get_secret_value(),
        http_client=client,
    )
    return OpenAIChatModel(model, provider=provider)
