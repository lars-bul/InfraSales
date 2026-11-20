"""Discovery's edge cases; suggesting through the API is tested in `test_router.py`."""

import pytest

from infrasales.feeds.discovery import NothingFoundError, discover
from infrasales.fetch.fetcher import Response, StatusError, Validators

pytestmark = pytest.mark.anyio


class Site:
    """A fake fetcher serving fixed bodies by URL; anything else is a 404."""

    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages

    async def fetch(
        self,
        url: str,
        validators: Validators | None = None,  # noqa: ARG002  # never conditional
    ) -> Response:
        if url not in self.pages:
            raise StatusError(Response(url, url, 404, {}, b""))
        return Response(url, url, 200, {}, self.pages[url])


async def test_an_empty_page_and_a_broken_gzip_sitemap_offer_nothing() -> None:
    site = Site({"https://news.test/": b"", "https://news.test/sitemap.xml": b"\x1f\x8bbroken"})

    with pytest.raises(NothingFoundError):
        await discover(site, "https://news.test/", no_sitemaps)


async def no_sitemaps(_: str) -> list[str]:
    return []
