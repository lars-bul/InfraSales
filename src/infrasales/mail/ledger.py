"""What the mailer remembers across a job's attempts: who already received a mail.

A job passes its run's steps (`JobContext.steps`), which keep these notes as long as the run
may be retried.
"""

from typing import Protocol


class Ledger(Protocol):
    async def recorded(self, prefix: str) -> frozenset[str]:
        """The names noted so far that start with `prefix`."""
        ...

    async def record(self, name: str) -> object:
        """Note `name` as done."""
        ...
