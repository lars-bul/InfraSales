import pytest
from pydantic import SecretStr, ValidationError

from infrasales.ai.providers import Provider
from infrasales.ai.schemas import ChatModel, ConnectionWrite, EmbeddingModel, Models


def test_the_mock_needs_no_model_but_a_service_does() -> None:
    assert ChatModel(provider="mock").model == ""

    with pytest.raises(ValidationError, match="needs a model"):
        ChatModel(provider=Provider.OPENROUTER)


@pytest.mark.parametrize(
    "model", ["qwen/qwen3-embedding-8b", "~provider/model-latest", "openai/gpt-oss-20b:free"]
)
def test_model_ids_as_the_services_name_them_are_accepted(model: str) -> None:
    assert EmbeddingModel(provider=Provider.OPENROUTER, model=model).model == model


@pytest.mark.parametrize("model", ["", "two words", "a\nb", "x" * 201])
def test_anything_else_is_no_model_id(model: str) -> None:
    with pytest.raises(ValidationError):
        EmbeddingModel(provider=Provider.OPENROUTER, model=model)


def test_models_survive_storage_as_json() -> None:
    models = Models(
        chat=ChatModel(provider=Provider.OPENROUTER, model="openai/gpt-oss-20b"),
        embedding=EmbeddingModel(provider=Provider.OPENROUTER, model="qwen/qwen3-embedding-8b"),
    )

    assert Models.model_validate(models.model_dump(mode="json")) == models


def test_a_key_is_written_but_never_shown() -> None:
    written = ConnectionWrite(api_key=SecretStr("sk-or-v1-secret"))

    assert "sk-or-v1-secret" not in repr(written)
    assert ConnectionWrite(api_key=None).api_key is None
