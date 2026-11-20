import pytest
from pydantic import ValidationError

from infrasales.ai.providers import Provider
from infrasales.core.secrets import new_key
from infrasales.settings import WorkerSettings


@pytest.fixture(autouse=True)
def _database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")


def test_without_a_provider_the_mock_chats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM__TRACE_CONTENT", "true")

    llm = WorkerSettings.load().llm

    assert (llm.provider, llm.model, llm.trace_content) == ("mock", "", True)


def test_the_environment_seeds_the_connection_and_every_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRETS_KEY", new_key())
    monkeypatch.setenv("OPENROUTER__API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM__PROVIDER", "openrouter")
    monkeypatch.setenv("LLM__MODEL", "mistralai/mistral-small")
    monkeypatch.setenv("EMBEDDING__MODEL", "baai/bge-m3")

    settings = WorkerSettings.load()

    assert settings.openrouter.api_key
    assert settings.openrouter.api_key.get_secret_value() == "sk-or-test"
    assert (settings.llm.provider, settings.llm.model) == ("openrouter", "mistralai/mistral-small")
    assert (settings.embedding.provider, settings.embedding.model) == ("openrouter", "baai/bge-m3")
    assert "sk-or-test" not in repr(settings)


def test_a_key_from_the_environment_needs_a_secrets_key_to_be_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER__API_KEY", "sk-or-test")

    with pytest.raises(ValidationError, match="SECRETS_KEY"):
        WorkerSettings.load()


def test_the_secrets_key_must_be_a_fernet_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRETS_KEY", "not-a-fernet-key")

    with pytest.raises(ValidationError, match="SECRETS_KEY"):
        WorkerSettings.load()


def test_chat_runs_on_a_named_service_or_the_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM__PROVIDER", "openai-compatible")

    with pytest.raises(ValidationError, match="openrouter"):
        WorkerSettings.load()


def test_embeddings_run_on_openrouter_by_default() -> None:
    settings = WorkerSettings.load()

    assert settings.embedding.provider is Provider.OPENROUTER
    assert settings.embedding.model == "qwen/qwen3-embedding-8b"


def test_blank_variables_from_an_unfilled_profile_are_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER__API_KEY", "")
    monkeypatch.setenv("LLM__MODEL", "")

    settings = WorkerSettings.load()

    assert (settings.openrouter.api_key, settings.llm.model) == (None, "")
