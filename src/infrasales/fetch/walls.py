"""Bot walls and block answers: the site refuses InfraSales' bot (ADR 03 §6).

InfraSales never tries to get around one: the Feed is marked blocked, an admin is alerted, and a
person decides (a licence, allow-listing). What counts as one, on any request:

- a bot-protection challenge, told by the headers the big walls send with it (Cloudflare's
  `cf-mitigated: challenge`, Vercel's `x-vercel-mitigated`, AWS WAF's `x-amzn-waf-action`), or by
  an error page naming the wall (Vercel's `429` "Vercel Security Checkpoint", Cloudflare's
  "Just a moment...", DataDome, PerimeterX, Imperva, Sucuri);
- a redirect to a wall's access page, which then answers `200`: a host named `unblock.` or
  `captcha.` (www.foerderregister.test sends bots to zugang.foerderregister.test, "Request
  Access"), DataDome's `captcha-delivery.com`, Cloudflare's `/cdn-cgi/challenge-platform/`.

Pages that answer `2xx` are never searched for markers: Cloudflare injects its challenge script
into ordinary pages too. A plain `429` or `503` is a busy site, not a wall.

A plain block answer (`401`, `403`, `451`) is `refused`: for one document it is that document's
failure (a members-only page, one article withheld in a country); for a Feed's listing request it
blocks the Feed, since nothing of it can be read then.

A wall stands in front of a site (`site`, `same_site`): the Feed's own blocks the Feed, another
site's (Heizungsforum links anywhere) only keeps InfraSales from that site for the run.
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

BLOCK_STATUSES = frozenset({401, 403, 451})
CHALLENGE_HEADERS = ("x-vercel-mitigated", "x-amzn-waf-action")  # sent with challenges only
MARKERS = (
    b"vercel security checkpoint",
    b"<title>just a moment...</title>",  # Cloudflare's challenge
    b"attention required! | cloudflare",
    b"captcha-delivery.com",  # DataDome
    b"px-captcha",  # PerimeterX (HUMAN)
    b"_incapsula_resource",  # Imperva
    b"sucuri website firewall",
)
WALL_HOST_LABELS = frozenset({"unblock", "captcha"})  # the first label of an access page's host
WALL_DOMAINS = ("captcha-delivery.com",)
WALL_PATHS = ("/cdn-cgi/challenge-platform/",)
_PEEK_BYTES = 64 << 10  # a wall says so at the top of its page
_ERROR = 400


def challenge(status: int, headers: Mapping[str, str], body: bytes) -> bool:
    """Whether the answer is a bot-protection challenge (`headers`: case-insensitive)."""
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    if any(name in headers for name in CHALLENGE_HEADERS):
        return True
    return status >= _ERROR and any(marker in body[:_PEEK_BYTES].lower() for marker in MARKERS)


def refused(status: int) -> bool:
    """Whether the answer is a block answer: no access to this document for InfraSales."""
    return status in BLOCK_STATUSES


def access_page(url: str) -> bool:
    """Whether `url` (where a request ended, after redirects) is a wall's access page."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return (
        host.split(".", 1)[0] in WALL_HOST_LABELS
        or any(host == domain or host.endswith(f".{domain}") for domain in WALL_DOMAINS)
        or any(parts.path.startswith(path) for path in WALL_PATHS)
    )


def site(url: str) -> str:
    """The host `url` is on, without `www.`: what a wall stands in front of."""
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def same_site(one: str, other: str) -> bool:
    """Whether two sites (`site`) are one: one host, or one a subdomain of the other.

    `feeds.heizwerk.test` and `heizwerk.test` are; `blog.example.com` and `news.example.com`
    are not, as no list of public suffixes says where a site begins.
    """
    return one == other or one.endswith(f".{other}") or other.endswith(f".{one}")
