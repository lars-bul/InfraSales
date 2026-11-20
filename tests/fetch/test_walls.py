"""What counts as a bot wall; the scrape job's reaction is tested through the job."""

import httpx2
import pytest

from infrasales.fetch.walls import challenge, refused, same_site, site

CHECKPOINT = b"<html><title>Vercel Security Checkpoint</title></html>"


@pytest.mark.parametrize(
    ("status", "headers", "body", "wall"),
    [
        (429, {}, CHECKPOINT, True),  # Vercel's checkpoint page
        (403, {"cf-mitigated": "challenge"}, b"", True),
        (202, {"x-amzn-waf-action": "captcha"}, b"", True),
        (503, {}, b"<title>Just a moment...</title>", True),
        (403, {}, b"Forbidden", False),  # a block answer, not a challenge
        (429, {}, b"Too many requests", False),  # busy, not walled
        (503, {}, b"Maintenance", False),
        (200, {}, b"<script src='/cdn-cgi/challenge-platform/x.js'></script>" + CHECKPOINT, False),
    ],
)
def test_challenges_are_told_from_block_answers_busy_sites_and_pages(
    status: int, headers: dict[str, str], body: bytes, *, wall: bool
) -> None:
    assert challenge(status, httpx2.Headers(headers), body) is wall


@pytest.mark.parametrize(
    ("status", "answer"), [(401, True), (403, True), (451, True), (429, False)]
)
def test_block_answers_refuse_the_document(status: int, *, answer: bool) -> None:
    assert refused(status) is answer


@pytest.mark.parametrize(
    ("url", "other", "same"),
    [
        (
            "https://www.trassenbau-report.test/netze/1",
            "https://trassenbau-report.test/rss/index.xml",
            True,
        ),
        ("https://heizwerk.test/netze/1", "https://feeds.heizwerk.test/heizwerk/index", True),
        ("https://zugang.foerderregister.test/", "https://www.foerderregister.test/", True),
        ("https://heizblog.medium.com/post", "https://medium.com/@someone/post", True),
        ("https://medium.com/@someone/post", "https://news.heizungsforum.test/", False),
        ("https://blog.example.com/a", "https://news.example.com/b", False),  # no suffix list
        ("https://notmedium.com/a", "https://medium.com/b", False),
    ],
)
def test_a_site_is_its_host_and_its_subdomains(url: str, other: str, *, same: bool) -> None:
    assert same_site(site(url), site(other)) is same
