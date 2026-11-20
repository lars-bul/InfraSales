"""robots.txt rules as read; how answers are read is tested through the scrape job."""

from protego import Protego

from infrasales.fetch.http import USER_AGENT
from infrasales.fetch.robots import NONE, UNREACHABLE, Rules

RULES = """
User-agent: *
Disallow: /

User-agent: InfraSalesBot
Disallow: /*?print=
Allow: /news/
Crawl-delay: 4
"""


def test_infrasales_follows_the_group_naming_it_wildcards_included() -> None:
    rules = Rules("allowed", Protego.parse(RULES))

    assert rules.allows("https://news.test/news/a", USER_AGENT)
    assert not rules.allows("https://news.test/news/a?print=1", USER_AGENT)
    assert rules.delay(USER_AGENT) == 4


def test_without_robots_txt_everything_is_allowed_unreachable_nothing() -> None:
    assert (NONE.allows("https://news.test/a", USER_AGENT), NONE.delay(USER_AGENT)) == (True, None)
    assert not UNREACHABLE.allows("https://news.test/a", USER_AGENT)
