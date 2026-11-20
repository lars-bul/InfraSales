"""Adding and listing Feeds through the API is tested in `test_router.py`."""

import pytest

from infrasales.feeds.service import slugify


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Netzbau Praxis Magazin", "netzbau-praxis-magazin"),
        ("  Oberste Baubehörde / News & Updates ", "oberste-baubehorde-news-updates"),
        ("Zürich Ägypten", "zurich-agypten"),
        ("新闻", "feed"),
        ("x" * 100, "x" * 60),
    ],
)
def test_slugs_are_lower_case_ascii_words(name: str, slug: str) -> None:
    assert slugify(name) == slug
