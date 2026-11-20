"""Validation of new Feeds through the API is tested in `test_router.py`."""

from infrasales.feeds.models import Feed, FeedCategory, FeedKind
from infrasales.feeds.schemas import FeedCreate, FeedRead


def test_a_feed_is_read_with_its_state() -> None:
    feed = Feed(name="News", slug="news", kind=FeedKind.RSS, url="https://news.test/feed")

    read = FeedRead.model_validate(
        feed.model_dump() | {"has_sources": False, "sources": 0}
    ).model_dump(mode="json")

    keys = ("slug", "category", "fetcher", "state", "enabled", "last_error", "has_sources")
    assert {k: read[k] for k in (*keys, "sources")} == {
        "slug": "news",
        "category": "press",
        "fetcher": "http",
        "state": "ok",
        "enabled": True,
        "last_error": None,
        "has_sources": False,
        "sources": 0,
    }


def test_a_new_feed_is_press_unless_it_says_otherwise() -> None:
    url = "https://news.test/feed"

    press = FeedCreate.model_validate({"name": "News", "kind": "rss", "url": url})
    utility = FeedCreate.model_validate(
        {"name": "Stadtwerke", "kind": "rss", "url": url, "category": "utility"}
    )

    assert (press.category, utility.category) == (FeedCategory.PRESS, FeedCategory.UTILITY)
