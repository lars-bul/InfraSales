"""The blocked-Feed notice's wording; when it is sent is tested through the scrape job."""

import uuid

from infrasales.feeds.alerts import FeedBlocked

RUN = uuid.UUID("0192f0c4-7e1a-7c3e-8a52-6f0e4c3b2a10")


def test_a_blocked_feed_notice_names_the_feed_and_what_a_person_decides() -> None:
    notice = FeedBlocked("waermewende", "Wärmewende", "https://waermewende.test/feed/", RUN)

    assert notice.subject() == "infrasales: the Feed waermewende is blocked"
    assert "Wärmewende (https://waermewende.test/feed/)" in notice.text()
    assert "nothing tries to get around" in notice.text()
    assert notice.key == f"feed-blocked-waermewende-{RUN}"  # not an alert mail's for the run
