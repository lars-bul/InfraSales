"""Telling people about failing jobs: the alert policy, then every configured channel.

A channel is a `Notifier` (`infrasales.scheduler.registry`): one more is a module here and a line in
`build_notifier`. Channels are imported only when configured.
"""

import asyncio
from collections.abc import Sequence

import structlog

from infrasales.alerts.settings import AlertSettings
from infrasales.mail.settings import SmtpSettings
from infrasales.scheduler.registry import Alert, Notice, Notifier

_log = structlog.stdlib.get_logger(__name__)


class Alerting:
    """The policy, then every channel at once: one failing never silences the others."""

    def __init__(self, channels: Sequence[Notifier], *, after_failures: int) -> None:
        self.channels = tuple(channels)
        self._after_failures = after_failures

    async def notify(self, notice: Notice) -> None:
        if (
            isinstance(notice, Alert)  # the policy is for failing runs: a job's findings all go out
            and notice.outcome == "retrying"
            and notice.attempt < self._after_failures
        ):
            return  # it is retried: no news yet
        sending = (channel.notify(notice) for channel in self.channels)
        outcomes = await asyncio.gather(*sending, return_exceptions=True)
        for channel, outcome in zip(self.channels, outcomes, strict=True):
            if isinstance(outcome, Exception):
                log = _log.bind(channel=type(channel).__name__, key=notice.key)
                log.error("alert.not_sent", exc_info=outcome)


def build_notifier(alerts: AlertSettings, smtp: SmtpSettings | None) -> Notifier | None:
    """The configured channels behind the alert policy; None if no channel is configured."""
    channels: list[Notifier] = []
    if alerts.recipients and smtp:
        # Loaded only when configured.
        from infrasales.alerts.mail import MailNotifier  # noqa: PLC0415

        channels.append(MailNotifier(smtp, alerts.recipients))
    if alerts.webhook_url:
        from infrasales.alerts.webhook import WebhookNotifier  # noqa: PLC0415  # likewise

        channels.append(WebhookNotifier(alerts.webhook_url.get_secret_value()))
    return Alerting(channels, after_failures=alerts.after_failures) if channels else None
