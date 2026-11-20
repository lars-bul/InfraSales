"""Decoding kept documents; through the scrape job: tests/jobs/test_scrape_extraction.py."""

import codecs

import pytest

from infrasales.extract.passthrough import PassthroughExtractor

URL = "https://api.test/notice"


@pytest.mark.parametrize(
    ("raw", "text"),
    [
        (codecs.BOM_UTF8 + b'{"a": "\xc3\xa9"}', '{"a": "é"}'),
        (
            b"<?xml version='1.0' encoding='no-such-codec'?><a>\xc3\xa9</a>",
            "<?xml version='1.0' encoding='no-such-codec'?><a>é</a>",
        ),
        (b'{"broken": "\xff"}', '{"broken": "\ufffd"}'),
    ],
)
def test_bytes_are_decoded_as_utf8_unless_said_otherwise_and_never_fail(
    raw: bytes, text: str
) -> None:
    assert PassthroughExtractor().extract(raw, URL).text == text
