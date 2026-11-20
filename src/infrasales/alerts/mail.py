"""Alerts by e-mail, through the report's SMTP setup: its timeouts, TLS and watchdog."""

from collections.abc import Sequence

from infrasales.mail.settings import SmtpSettings
from infrasales.mail.smtp import SmtpMailer
from infrasales.scheduler.registry import Notice


class MailNotifier:
    def __init__(self, smtp: SmtpSettings, recipients: Sequence[str]) -> None:
        self._mailer = SmtpMailer(smtp.model_copy(update={"recipients": list(recipients)}))

    async def notify(self, notice: Notice) -> None:
        key = notice.key  # also the mail's Message-ID
        await self._mailer.send(notice.subject(), notice.text(), key=key, ledger=_Unrecorded())


class _Unrecorded:
    """Alerts are not resumed: nothing is noted, each alert goes to everyone once."""

    async def recorded(self, prefix: str) -> frozenset[str]:  # noqa: ARG002  # noted: nothing
        return frozenset()

    async def record(self, name: str) -> None:
        pass
