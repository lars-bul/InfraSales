import pytest
from pydantic import BaseModel, ValidationError

from infrasales.core.fields import CommaSeparated, ExactUrl


class Example(BaseModel):
    values: CommaSeparated = []
    url: ExactUrl = "https://example.org"


def test_comma_separated_text_becomes_a_list_and_lists_stay_lists() -> None:
    assert Example.model_validate({"values": " a, b ,,c "}).values == ["a", "b", "c"]
    assert Example.model_validate({"values": ["a", "b"]}).values == ["a", "b"]


@pytest.mark.parametrize("url", ["https://idp.test", "https://idp.test/", "http://idp.test/a/"])
def test_exact_urls_are_kept_as_given(url: str) -> None:
    assert Example.model_validate({"url": url}).url == url  # HttpUrl would add or drop a "/"


def test_exact_urls_must_be_urls() -> None:
    with pytest.raises(ValidationError, match="url"):
        Example.model_validate({"url": "idp.test"})
