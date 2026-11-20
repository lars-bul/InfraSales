"""Sending mail: an SMTP server when one is configured, otherwise the log."""

from typing import Protocol

import structlog

from infrasales.mail.ledger import Ledger
from infrasales.mail.settings import SmtpSettings

_log = structlog.stdlib.get_logger(__name__)


class Mailer(Protocol):
    async def send(
        self, subject: str, body: str, *, key: str, ledger: Ledger, html: str | None = None
    ) -> int:
        """Send a text mail, `html` its alternative, to every recipient, at least once each.

        Returns how many it reached now.

        `key` identifies the mail (e.g. per job run); `ledger` keeps who received it. Raises if
        a recipient could not be reached: sending again with the same key and ledger then mails
        the recipients still missing only.
        """
        ...


class LogMailer:
    """No SMTP server configured: the mail is logged, not sent."""

    async def send(
        self,
        subject: str,
        body: str,
        *,
        key: str,
        ledger: Ledger,  # noqa: ARG002  # nothing delivered, nothing noted
        html: str | None = None,  # noqa: ARG002  # the text is logged
    ) -> int:
        _log.info("mail not configured, not sent", subject=subject, body=body, key=key)
        return 0


def build_mailer(settings: SmtpSettings | None) -> Mailer:
    if settings is None:
        return LogMailer()
    from infrasales.mail.smtp import SmtpMailer

    return SmtpMailer(settings)
