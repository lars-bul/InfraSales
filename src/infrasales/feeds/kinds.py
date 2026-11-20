"""The Lister of each Feed kind. A new kind: one Lister module and one line below.

A kind without a Lister here (yet) cannot be read: such a Feed fails with "no lister".
"""

from collections.abc import Mapping

from infrasales.core.failures import ExpectedError
from infrasales.feeds.lister import Lister
from infrasales.feeds.models import FeedKind
from infrasales.feeds.rss import RssLister
from infrasales.feeds.sitemap import SitemapLister

LISTERS: Mapping[FeedKind, Lister] = {
    FeedKind.RSS: RssLister(),
    FeedKind.SITEMAP: SitemapLister(),
}


class NoListerError(ExpectedError):
    """No Lister reads Feeds of this kind."""

    reason = "no lister"


def lister_for(kind: FeedKind) -> Lister:
    try:
        return LISTERS[kind]
    except KeyError:
        msg = f"no Lister for Feeds of kind {kind}"
        raise NoListerError(msg) from None
