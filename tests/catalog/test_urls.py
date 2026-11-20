import hashlib

import pytest

from infrasales.catalog.urls import MalformedUrlError, normalize_url, url_hash


@pytest.mark.parametrize(
    ("listed", "normalised"),
    [
        ("HTTPS://News.Test/a/", "https://news.test/a"),
        ("https://news.test/a?utm_source=rss&id=7&fbclid=x#top", "https://news.test/a?id=7"),
        ("https://news.test", "https://news.test/"),
        (" https://news.test/a?mc_cid=1&q= ", "https://news.test/a?q="),
        ("https://news.test/a?b=2&a=1&a=0", "https://news.test/a?a=0&a=1&b=2"),  # sorted
        ("https://news.test:443/a", "https://news.test/a"),  # the default port
        ("http://news.test:80/a", "http://news.test/a"),
        ("http://news.test:8080/a", "http://news.test:8080/a"),  # another port: another site
        ("https://jane:secret@News.Test/a", "https://news.test/a"),  # no user, no password
        ("http://[2001:DB8::1]:80/a", "http://[2001:db8::1]/a"),
    ],
)
def test_one_address_however_it_is_linked(listed: str, normalised: str) -> None:
    assert normalize_url(listed) == normalised


@pytest.mark.parametrize(
    "listed",
    [
        "http://[::1/broken",  # an IPv6 host without its bracket
        "https://news.test:99999/a",  # no port
        "https://news.test:http/a",
        "https://news.test/a\x00b",  # a control character
        "https://news.test/a\x7f",
    ],
)
def test_what_is_no_url_is_a_malformed_address(listed: str) -> None:
    with pytest.raises(MalformedUrlError) as raised:
        normalize_url(listed)

    assert raised.value.reason == "malformed address"


def test_the_hash_is_sha256_of_the_normalised_url() -> None:
    assert url_hash("https://news.test/a") == hashlib.sha256(b"https://news.test/a").hexdigest()
