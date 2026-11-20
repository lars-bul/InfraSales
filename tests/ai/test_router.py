from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx2
import pytest

from infrasales.ai.router import AI, AiContext
from infrasales.app import create_app
from infrasales.settings import Settings
from tests.helpers import SAME_ORIGIN, audit_actions, sign_in

pytestmark = pytest.mark.anyio
FIRST = SAME_ORIGIN | {"if-match": '"1"'}
OPENROUTER = "/api/ai/connections/openrouter"
MODELS = {
    "chat": {"provider": "openrouter", "model": "mistralai/mistral-small"},
    "embedding": {"provider": "openrouter", "model": "qwen/qwen3-embedding-8b"},
}


@pytest.fixture
async def keyless(settings: Settings) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app(settings.model_copy(update={"secrets_key": None}))
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        yield client


async def test_only_admins_read_the_ai_settings(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/api/ai")).status_code == 401
    await sign_in(client, "vera")
    assert (await client.get("/api/ai")).status_code == 403
    await sign_in(client, "alice")

    body = (await client.get("/api/ai")).json()

    assert [(c["provider"], c["key"], c["revision"]) for c in body["connections"]] == [
        ("openrouter", "unset", 1),
    ]
    assert body["models"]["chat"] == {"provider": "mock", "model": ""}
    assert body["keys_storable"] is True


async def test_a_stored_key_is_never_sent_back(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "alice")

    response = await client.put(
        "/api/ai/connections/openrouter", json={"api_key": "sk-or-v1-secret"}, headers=FIRST
    )

    assert response.status_code == 200
    assert (response.json()["key"], response.headers["etag"]) == ("set", '"2"')
    assert "sk-or-v1-secret" not in response.text
    assert "sk-or-v1-secret" not in (await client.get("/api/ai")).text
    assert (await audit_actions(database_url))[-1] == (
        "basic:alice",
        "ai.connection.updated",
        "success",
    )


async def test_a_key_is_removed_with_null(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")
    await client.put(OPENROUTER, json={"api_key": "sk-or-v1-first"}, headers=FIRST)

    response = await client.put(
        "/api/ai/connections/openrouter",
        json={"api_key": None},
        headers=SAME_ORIGIN | {"if-match": '"2"'},
    )

    assert response.json()["key"] == "unset"


async def test_a_change_to_another_revision_is_refused(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")
    await client.put(OPENROUTER, json={"api_key": "sk-or-v1-first"}, headers=FIRST)

    again = await client.put(
        "/api/ai/connections/openrouter", json={"api_key": "sk-or-v1-second"}, headers=FIRST
    )
    malformed = await client.put(
        "/api/ai/models", json=MODELS, headers=SAME_ORIGIN | {"if-match": "1"}
    )

    assert (again.status_code, malformed.status_code) == (412, 412)


@pytest.mark.parametrize(
    "api_key", ["short", "sk-or-v1\nInjected: header", " sk-or-v1-padded", "x" * 513]
)
async def test_a_key_must_be_one_plausible_token(client: httpx2.AsyncClient, api_key: str) -> None:
    await sign_in(client, "alice")

    response = await client.put(
        "/api/ai/connections/openrouter", json={"api_key": api_key}, headers=FIRST
    )

    assert response.status_code == 422
    assert api_key not in response.text


async def test_without_a_secrets_key_no_key_can_be_stored(keyless: httpx2.AsyncClient) -> None:
    await sign_in(keyless, "alice")

    response = await keyless.put(
        "/api/ai/connections/openrouter", json={"api_key": "sk-or-v1-secret"}, headers=FIRST
    )

    assert response.status_code == 409
    assert "SECRETS_KEY" in response.json()["detail"]
    assert (await keyless.get("/api/ai")).json()["keys_storable"] is False


async def test_admins_choose_the_models(client: httpx2.AsyncClient, database_url: str) -> None:
    await sign_in(client, "alice")

    response = await client.put("/api/ai/models", json=MODELS, headers=FIRST)

    assert response.status_code == 200
    assert (await client.get("/api/ai")).json()["models"] == response.json()
    assert {key: response.json()[key] for key in MODELS} == MODELS
    assert (await audit_actions(database_url))[-1][1] == "ai.models.updated"


@pytest.mark.parametrize(
    "change",
    [
        {"chat": {"provider": "openai", "model": "gpt"}},
        {"chat": {"provider": "openrouter", "model": ""}},
        {"embedding": {"provider": "mock", "model": "x"}},
        {"embedding": {"provider": "openrouter", "model": "two words"}},
        {"embedding": {"provider": "openrouter", "model": "a" * 201}},
    ],
)
async def test_a_model_choice_is_validated(
    client: httpx2.AsyncClient, change: dict[str, object]
) -> None:
    await sign_in(client, "alice")

    response = await client.put("/api/ai/models", json=MODELS | change, headers=FIRST)

    assert response.status_code == 422


async def test_viewers_cannot_change_ai_settings(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "vera")

    key = await client.put("/api/ai/connections/openrouter", json={"api_key": None}, headers=FIRST)
    models = await client.put("/api/ai/models", json=MODELS, headers=FIRST)

    assert (key.status_code, models.status_code) == (403, 403)


async def test_ai_settings_are_not_part_of_the_configuration_viewers_read(
    client: httpx2.AsyncClient,
) -> None:
    await sign_in(client, "vera")

    keys = [entry["key"] for entry in (await client.get("/api/config")).json()]

    assert keys == ["forecast_schedule", "scrape_schedule"]


@asynccontextmanager
async def listing(
    settings: Settings, answer: Callable[[httpx2.Request], httpx2.Response]
) -> AsyncGenerator[tuple[httpx2.AsyncClient, list[httpx2.Request]]]:
    asked: list[httpx2.Request] = []

    def service(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        return answer(request)

    app = create_app(settings)
    AI.set(app, AiContext(settings, settings.secret_box(), httpx2.MockTransport(service)))
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        yield client, asked


LISTED = {"data": [{"id": "openai/gpt-oss-20b", "name": "OpenAI: gpt-oss-20b"}]}
MODELS_OF = "/api/ai/connections/openrouter/models"


async def test_admins_list_a_services_models_with_its_stored_key(settings: Settings) -> None:
    async with listing(settings, lambda _: httpx2.Response(200, json=LISTED)) as (client, asked):
        await sign_in(client, "vera")
        assert (await client.get(MODELS_OF, params={"purpose": "chat"})).status_code == 403
        await sign_in(client, "alice")
        await client.put(OPENROUTER, json={"api_key": "sk-or-v1-first"}, headers=FIRST)

        response = await client.get(MODELS_OF, params={"purpose": "chat"})

    assert response.json() == [{"id": "openai/gpt-oss-20b", "name": "OpenAI: gpt-oss-20b"}]
    (request,) = asked
    assert request.headers["authorization"] == "Bearer sk-or-v1-first"


@pytest.mark.parametrize(("status", "answered"), [(401, 409), (503, 502)])
async def test_a_service_that_will_not_list_its_models_says_why(
    settings: Settings, status: int, answered: int
) -> None:
    async with listing(settings, lambda _: httpx2.Response(status, json={})) as (client, _):
        await sign_in(client, "alice")

        response = await client.get(MODELS_OF, params={"purpose": "embedding"})

    assert response.status_code == answered


async def test_models_are_listed_for_a_purpose(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")

    assert (await client.get(MODELS_OF)).status_code == 422
    assert (await client.get(MODELS_OF, params={"purpose": "poetry"})).status_code == 422
