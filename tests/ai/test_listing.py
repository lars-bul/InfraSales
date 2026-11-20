import httpx2
import pytest
from pydantic import SecretStr

from infrasales.ai.listing import (
    KeyRefusedError,
    ModelOption,
    ModelsUnavailableError,
    Purpose,
    available,
)
from infrasales.ai.providers import Provider

pytestmark = pytest.mark.anyio
KEY = SecretStr("sk-test")
OPENROUTER_CHAT = {
    "data": [
        {
            "id": "z-ai/glm-5",
            "name": "Z.ai: GLM 5",
            "architecture": {"output_modalities": ["text"]},
        },
        {"id": "openai/gpt-oss-20b", "name": "OpenAI: gpt-oss-20b"},
        {"id": "not a model id", "name": "Broken"},
    ]
}
OPENROUTER_EMBEDDINGS = {"data": [{"id": "qwen/qwen3-embedding-8b", "name": "Qwen3 Embedding 8B"}]}


class Service:
    def __init__(self, status: int = 200, body: object = None) -> None:
        self.status, self.body = status, body
        self.asked: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.asked.append(request)
        if self.body is not None:
            return httpx2.Response(self.status, json=self.body)
        path = request.url.path
        body = OPENROUTER_EMBEDDINGS if path.endswith("/embeddings/models") else OPENROUTER_CHAT
        return httpx2.Response(self.status, json=body)


async def listed(
    provider: Provider, purpose: Purpose, service: Service, key: SecretStr | None = KEY
) -> list[ModelOption]:
    return await available(provider, purpose, key, httpx2.MockTransport(service))


async def test_openrouter_lists_its_chat_models_by_id_without_what_could_not_be_saved() -> None:
    service = Service()

    models = await listed(Provider.OPENROUTER, Purpose.CHAT, service)

    assert models == [
        ModelOption(id="openai/gpt-oss-20b", name="OpenAI: gpt-oss-20b"),
        ModelOption(id="z-ai/glm-5", name="Z.ai: GLM 5"),
    ]
    (request,) = service.asked
    assert str(request.url) == "https://openrouter.ai/api/v1/models"
    assert request.headers["authorization"] == "Bearer sk-test"


async def test_openrouter_lists_its_embedding_models_apart() -> None:
    service = Service()

    models = await listed(Provider.OPENROUTER, Purpose.EMBEDDING, service)

    assert [model.id for model in models] == ["qwen/qwen3-embedding-8b"]
    assert str(service.asked[0].url) == "https://openrouter.ai/api/v1/embeddings/models"


async def test_without_a_key_openrouter_lists_what_anyone_may_use() -> None:
    service = Service()

    await listed(Provider.OPENROUTER, Purpose.CHAT, service, key=None)

    assert "authorization" not in service.asked[0].headers


@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_key_says_so(status: int) -> None:
    with pytest.raises(KeyRefusedError):
        await listed(Provider.OPENROUTER, Purpose.CHAT, Service(status, {"error": "no"}))


@pytest.mark.parametrize(
    "service", [Service(503, {"error": "down"}), Service(200, {"models": []}), Service(200, [])]
)
async def test_a_service_that_does_not_list_its_models_is_unavailable(service: Service) -> None:
    with pytest.raises(ModelsUnavailableError):
        await listed(Provider.OPENROUTER, Purpose.CHAT, service)
