"""One address per Source: URLs are normalised before they are looked up or stored.

Ported from the draft branch `feat/core-foundation-scraper` (lars-bul). Normalised as RFC 3986
§6.2 allows (lower-case scheme and host, the scheme's default port dropped), with the query's
parameters sorted and tracking parameters dropped, so one page does not become two Sources.
User and password (`user:password@`, which RFC 9110 §4.2.4 forbids in http(s) URLs) are
dropped: no password is stored.
"""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from infrasales.core.failures import ExpectedError

_TRACKING = frozenset({"fbclid", "gclid"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")  # what urlsplit leaves of them: no URL holds any


class MalformedUrlError(ExpectedError):
    """The address cannot be read as a URL: the document it names is skipped."""

    reason = "malformed address"


def normalize_url(url: str) -> str:
    """Lower-case scheme and host, no default port, user, trailing slash, fragment or tracking.

    Raises `MalformedUrlError` for what no URL is (a bad IPv6 host or port, a control character).
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as error:
        msg = f"not a URL: {url!r} ({error})"
        raise MalformedUrlError(msg) from None
    if _CONTROL.search(parts.geturl()):
        msg = f"a control character in {url!r}"
        raise MalformedUrlError(msg)
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    if ":" in host:  # IPv6
        host = f"[{host}]"
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        host = f"{host}:{port}"
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(("utm_", "mc_")) and key.lower() not in _TRACKING
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def url_hash(normalized: str) -> str:
    """The key a Source is looked up by: sha256 (hex) of its normalised URL."""
    return hashlib.sha256(normalized.encode()).hexdigest()
