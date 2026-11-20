"""An alert to send, and a notifier that records what it is told."""

import asyncio
import uuid
from dataclasses import dataclass, field

from infrasales.scheduler.registry import Alert, Notice

RUN = uuid.UUID("0192f0c4-7e1a-7c3e-8a52-6f0e4c3b2a10")
FAILED = Alert(
    job="report",
    run_id=RUN,
    outcome="failed",
    attempt=3,
    max_attempts=3,
    error="TimeoutError",
    langfuse_url=f"https://langfuse.test/project/p1/sessions/{RUN}",
)


@dataclass
class RecordingNotifier:
    """Records each notice (failing runs also in `alerts`); then fails with `error`, or hangs."""

    alerts: list[Alert] = field(default_factory=list[Alert])
    notices: list[Notice] = field(default_factory=list[Notice])  # every one, alerts included
    error: Exception | None = None
    hangs: bool = False

    async def notify(self, notice: Notice) -> None:
        self.notices.append(notice)
        if isinstance(notice, Alert):
            self.alerts.append(notice)
        if self.hangs:
            await asyncio.Event().wait()
        if self.error:
            raise self.error
