import pytest
from pydantic import ValidationError

from infrasales.catalog.schemas import SourceQuery


def test_a_search_is_trimmed_and_a_blank_one_searches_nothing() -> None:
    assert SourceQuery(q="  wärmenetz  ").q == "wärmenetz"
    assert SourceQuery(q="   ").q == ""  # the listing ignores an empty search


@pytest.mark.parametrize("limit", [0, 51])
def test_a_page_holds_1_to_50_sources(limit: int) -> None:
    with pytest.raises(ValidationError):
        SourceQuery(limit=limit)


def test_a_search_is_at_most_200_characters() -> None:
    with pytest.raises(ValidationError):
        SourceQuery(q="x" * 201)
