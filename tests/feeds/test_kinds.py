import pytest

from infrasales.feeds import kinds
from infrasales.feeds.kinds import NoListerError, lister_for
from infrasales.feeds.models import FeedKind
from infrasales.feeds.rss import RssLister


def test_rss_feeds_are_read_by_the_rss_lister() -> None:
    assert isinstance(lister_for(FeedKind.RSS), RssLister)


def test_a_kind_without_a_lister_cannot_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(kinds.LISTERS, FeedKind.RSS)

    with pytest.raises(NoListerError):
        lister_for(FeedKind.RSS)
