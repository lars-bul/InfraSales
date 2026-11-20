"""Mail over SMTP with the standard library: one session per mail, in a thread of its own.

Each recipient gets their own copy, so nobody sees the other addresses. Delivery is at least
once per recipient and resumable: every accepted copy is noted in the ledger at once (a hash of
the address, never the address), and sending again under the same key mails the recipients
still missing only.

Each copy, sent and noted, takes at most `SMTP__TIMEOUT_SECONDS`, and a cancelled delivery ends
within that time too: below the scheduler's stop margin, so no copy is in flight when a run
passes to another worker, and a stuck server or database never holds a shutdown. Neither does a
stuck connection attempt (DNS, which no timeout bounds): the session's thread is not waited
for at exit, and once stopped it sends nothing more.
"""

import asyncio
import contextlib
import hashlib
import smtplib
import socket
import ssl
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate
from functools import partial
from typing import cast

import structlog

from infrasales.core.tasks import finish_within, in_thread
from infrasales.mail.ledger import Ledger
from infrasales.mail.settings import SmtpSettings, mailbox

_log = structlog.stdlib.get_logger(__name__)


def _delivered(key: str, address: str) -> str:
    """The ledger's name for `address` having received the mail `key`."""
    return f"{key} {hashlib.sha256(mailbox(address).encode()).hexdigest()}"


class MailNotDeliveredError(Exception):
    """Some recipients' servers refused the mail: the run fails, and its retry tries again."""

    def __init__(self, refused: int, of: int) -> None:
        super().__init__(f"{refused} of {of} recipients refused the mail")


class MailNotNotedError(Exception):
    """A copy was accepted but could not be noted in time (the database stalled).

    Its outcome is then unknown to the ledger: the run's retry sends it again, so this one
    recipient may get the mail twice. The session stops: no further copy goes out unnoted.
    """


@dataclass(frozen=True, slots=True)
class _Mail:
    subject: str
    body: str
    key: str
    html: str | None = None


class SmtpMailer:
    def __init__(self, settings: SmtpSettings) -> None:
        self._settings = settings

    async def send(
        self, subject: str, body: str, *, key: str, ledger: Ledger, html: str | None = None
    ) -> int:
        recipients = self._settings.recipients
        reached = await ledger.recorded(f"{key} ")
        missing = [to for to in recipients if _delivered(key, to) not in reached]
        log = _log.bind(key=key, recipients=len(recipients))  # counts only: addresses are personal
        if not missing:
            log.info("mail already sent")
            return 0
        if refused := await self._deliver(_Mail(subject, body, key, html), missing, ledger):
            log.warning("mail refused", refused=refused, missing=len(missing))
            raise MailNotDeliveredError(refused, len(missing))
        log.info("mail sent", subject=subject, sent=len(missing), resumed=bool(reached))
        return len(missing)

    async def _deliver(self, mail: _Mail, recipients: Sequence[str], ledger: Ledger) -> int:
        """Send each recipient their copy over one connection; how many refused it.

        Cancelled meanwhile (shutdown, timeout, a lost lease), no further copy starts, the one
        in flight may finish and be noted, and the cancellation takes effect within the SMTP
        timeout at the latest.
        """
        loop, stop = asyncio.get_running_loop(), threading.Event()

        def note(to: str, by: float) -> None:
            """In the thread: note `to`'s copy, waiting for the database until `by` at most."""
            noting = asyncio.run_coroutine_threadsafe(ledger.record(_delivered(mail.key, to)), loop)
            try:
                noting.result(timeout=max(by - time.monotonic(), 0))
            except TimeoutError as error:
                noting.cancel()
                raise MailNotNotedError from error

        session = in_thread(partial(self._session, mail, recipients, note, stop), name="smtp")
        return await finish_within(session, stop=stop.set, grace=self._settings.timeout_seconds)

    def _session(
        self,
        mail: _Mail,
        recipients: Sequence[str],
        note: Callable[[str, float], None],
        stop: threading.Event,
    ) -> int:
        """In the thread: one connection, a copy per recipient, each built just before it goes."""
        timeout, refused = self._settings.timeout_seconds, 0
        server = self._connect()
        try:
            _guarded(server, partial(self._log_in, server), time.monotonic() + timeout)
            for to in recipients:
                if stop.is_set():
                    break
                by = time.monotonic() + timeout  # the copy is sent and noted by then
                try:
                    _guarded(server, partial(server.send_message, self._copy(mail, to)), by)
                except smtplib.SMTPRecipientsRefused:
                    refused += 1
                else:
                    note(to, by)
        finally:
            self._close(server, polite=not stop.is_set())
        return refused

    def _connect(self) -> smtplib.SMTP:
        settings = self._settings
        if settings.security == "tls":
            return smtplib.SMTP_SSL(
                settings.host, settings.port, timeout=settings.timeout_seconds, context=_tls()
            )
        return smtplib.SMTP(settings.host, settings.port, timeout=settings.timeout_seconds)

    def _log_in(self, server: smtplib.SMTP) -> None:
        settings = self._settings
        if settings.security == "starttls":
            server.starttls(context=_tls())
        if settings.username and settings.password:
            server.login(settings.username, settings.password.get_secret_value())

    def _close(self, server: smtplib.SMTP, *, polite: bool) -> None:
        """Say QUIT when done; when stopped, close at once: QUIT is one more wait on the server."""
        if polite:
            by = time.monotonic() + self._settings.timeout_seconds
            with contextlib.suppress(smtplib.SMTPServerDisconnected):  # cut, or gone already
                _guarded(server, server.quit, by)
        server.close()

    def _copy(self, mail: _Mail, to: str) -> EmailMessage:
        settings = self._settings
        message = EmailMessage()
        message["From"] = settings.sender
        message["To"] = to  # this recipient only
        message["Subject"] = mail.subject
        message["Date"] = formatdate(usegmt=True)
        # The same for every copy and every retry: a duplicate is recognisably the same mail.
        message["Message-ID"] = f"<{mail.key}@{settings.sender.partition('@')[2]}>"
        message.set_content(mail.body)
        if mail.html is not None:
            message.add_alternative(mail.html, subtype="html")
        return message


def _guarded[T](server: smtplib.SMTP, step: Callable[[], T], by: float) -> T:
    """Run `step`, cutting the connection at `by`: however slow the server, it ends by then.

    smtplib's timeout limits each socket operation, and a slow server can string many of them
    together. A step cut off has an unknown outcome: a copy is then not noted, and sent again.
    The watchdog holds a descriptor of its own for the connection: STARTTLS replaces (and
    detaches) the socket object mid-step, and the connection is cut all the same.
    """
    sock = cast("socket.socket", server.sock)  # set since _connect
    with socket.fromfd(sock.fileno(), sock.family, sock.type) as connection:
        watchdog = threading.Timer(max(by - time.monotonic(), 0), _cut, (connection,))
        watchdog.start()
        try:
            return step()
        finally:
            watchdog.cancel()
            watchdog.join()  # a cut under way ends before its descriptor is closed


def _cut(connection: socket.socket) -> None:
    """End the connection from another thread: a blocked send or read fails at once.

    Shutting down acts on the connection, not the descriptor: whatever object wraps it now.
    """
    with contextlib.suppress(OSError):  # closed meanwhile: nothing left to cut
        connection.shutdown(socket.SHUT_RDWR)


def _tls() -> ssl.SSLContext:
    return ssl.create_default_context()  # verifies the server's certificate and host name
