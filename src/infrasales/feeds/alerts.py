"""What admins hear about a Feed: its site blocks InfraSales' bot (ADR 03 §6).

Sent through the jobs' notifier (the alert channels) when a Feed becomes blocked, not on every
run it stays blocked: a person decides what to do (a licence, allow-listing); InfraSales never
tries to get around the wall.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeedBlocked:
    feed: str  # its slug
    name: str
    url: str
    run_id: uuid.UUID | None  # the run that found it blocked; None: not run by the scheduler

    @property
    def key(self) -> str:
        return f"feed-blocked-{self.feed}-{self.run_id}"

    def subject(self) -> str:
        return f"infrasales: the Feed {self.feed} is blocked"

    def text(self) -> str:
        return (
            f"The site of the Feed {self.name} ({self.url}) blocks InfraSales' bot: a bot wall "
            "or a block answer. The Feed is marked blocked and is read again each run; "
            "nothing tries to get around the block. A person decides what to do (a licence, "
            f"allow-listing).\nRun: {self.run_id}"
        )
