import asyncio
import io
import json
import smtplib
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator
from email.message import EmailMessage
from typing import Literal

import pytest
from pydantic import SecretStr, ValidationError

from infrasales.core.db import Database
from infrasales.core.logs import configure_logging
from infrasales.mail import smtp as mail_smtp
from infrasales.mail.settings import SmtpSettings
from infrasales.mail.smtp import MailNotDeliveredError, MailNotNotedError, SmtpMailer
from infrasales.scheduler.steps import Steps
from tests.mail.support import FakeSmtp
from tests.scheduler.support import queued_run

pytestmark = pytest.mark.anyio
ALICE, BOB = "alice@example.org", "bob@example.org"


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> FakeSmtp:
    return FakeSmtp.installed(monkeypatch)


@pytest.fixture
async def ledger(database_url: str) -> AsyncIterator[Steps]:
    """Where the mailer notes who received a mail: a run's steps, as jobs pass them."""
    db = Database(database_url)
    yield Steps(db, await queued_run(db))
    await db.dispose()


def _settings(
    security: Literal["starttls", "tls", "none"] = "none", **extra: object
) -> SmtpSettings:
    return SmtpSettings.model_validate(
        {
            "host": "smtp.example.org",
            "security": security,
            "sender": "infrasales@example.org",
            "recipients": [ALICE, BOB],
        }
        | extra
    )


async def _reached(ledger: Steps, key: str = "report-1") -> frozenset[str]:
    return await ledger.recorded(f"{key} ")


async def test_each_recipient_gets_their_own_copy_and_is_recorded(
    smtp: FakeSmtp, ledger: Steps
) -> None:
    settings = _settings("starttls", username="infrasales", password=SecretStr("secret"))

    await SmtpMailer(settings).send("Weekly", "Hello world", key="report-1", ledger=ledger)

    (server,) = smtp.servers  # one connection for all copies
    assert server.address == ("smtp.example.org", 587)
    assert server.steps == [
        "starttls",
        "login infrasales:secret",
        f"send {ALICE}",
        f"send {BOB}",
        "quit",
    ]
    assert [message["To"] for message in server.sent] == [ALICE, BOB]  # nobody sees the other
    for message in server.sent:
        assert (message["From"], message["Subject"]) == ("infrasales@example.org", "Weekly")
        assert message["Message-ID"] == "<report-1@example.org>"  # the same for a retry
        assert message.get_content().strip() == "Hello world"
    reached = await _reached(ledger)
    assert len(reached) == 2
    assert not [name for name in reached if "example.org" in name]  # hashes, never addresses


async def test_an_html_alternative_goes_with_the_text(smtp: FakeSmtp, ledger: Steps) -> None:
    html = "<!doctype html><p>Hello <b>world</b></p>"

    await SmtpMailer(_settings("none")).send(
        "Weekly", "Hello world", key="report-2", ledger=ledger, html=html
    )

    for message in smtp.servers[0].sent:
        text, rich = message.iter_parts()
        assert (text.get_content_type(), rich.get_content_type()) == ("text/plain", "text/html")
        assert rich.get_content().strip() == html


@pytest.mark.parametrize(("security", "implicit_tls"), [("tls", True), ("none", False)])
async def test_implicit_tls_or_plain_without_login(
    smtp: FakeSmtp,
    ledger: Steps,
    security: Literal["tls", "none"],
    *,
    implicit_tls: bool,
) -> None:
    await SmtpMailer(_settings(security)).send("Weekly", "Hello world", key="k", ledger=ledger)

    (server,) = smtp.servers
    assert (server.implicit_tls, server.steps) == (
        implicit_tls,
        [f"send {ALICE}", f"send {BOB}", "quit"],
    )


async def test_a_refusal_fails_the_send_and_the_retry_mails_only_the_missing(
    smtp: FakeSmtp, ledger: Steps
) -> None:
    """The guarantee: never reported as sent unless everyone got it, never sent twice."""
    configure_logging(stream=io.StringIO())
    mailer = SmtpMailer(_settings())
    smtp.failing[BOB] = smtplib.SMTPRecipientsRefused({BOB: (450, b"mailbox busy")})

    with pytest.raises(MailNotDeliveredError, match="1 of 2 recipients refused"):
        await mailer.send("Weekly", "Hello world", key="report-1", ledger=ledger)
    smtp.failing.clear()
    sent = await mailer.send("Weekly", "Hello world", key="report-1", ledger=ledger)  # retry

    assert sent == 1  # Bob's copy only
    first, retry = smtp.servers
    assert first.steps == [f"send {ALICE}", "quit"]
    assert retry.steps == [f"send {BOB}", "quit"]  # Alice is not mailed twice
    assert len(await _reached(ledger)) == 2


async def test_a_lost_connection_keeps_what_was_delivered(smtp: FakeSmtp, ledger: Steps) -> None:
    mailer = SmtpMailer(_settings())
    smtp.failing[BOB] = smtplib.SMTPServerDisconnected("connection lost")

    with pytest.raises(smtplib.SMTPServerDisconnected):
        await mailer.send("Weekly", "Hello world", key="report-1", ledger=ledger)
    smtp.failing.clear()
    await mailer.send("Weekly", "Hello world", key="report-1", ledger=ledger)

    assert [server.steps for server in smtp.servers] == [
        [f"send {ALICE}", "quit"],
        [f"send {BOB}", "quit"],
    ]


async def test_a_recipient_listed_twice_gets_one_copy(smtp: FakeSmtp, ledger: Steps) -> None:
    settings = _settings(recipients=[ALICE, BOB, ALICE.upper(), f" {BOB}"])

    await SmtpMailer(settings).send("Weekly", "Hello world", key="report-1", ledger=ledger)

    (server,) = smtp.servers
    assert server.steps == [f"send {ALICE}", f"send {BOB}", "quit"]


async def test_a_delivered_mail_is_not_sent_again(smtp: FakeSmtp, ledger: Steps) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    mailer = SmtpMailer(_settings())

    first = await mailer.send("Weekly", "Hello world", key="report-1", ledger=ledger)
    again = await mailer.send("Weekly", "Hello world", key="report-1", ledger=ledger)

    assert (first, again) == (2, 0)  # copies sent by each call
    assert len(smtp.servers) == 1
    events = [json.loads(line)["event"] for line in stream.getvalue().splitlines()]
    assert events == ["mail sent", "mail already sent"]
    assert ALICE not in stream.getvalue()  # addresses are not logged


async def test_cancelling_finishes_the_copy_in_flight_then_stops(
    smtp: FakeSmtp, ledger: Steps
) -> None:
    """A shutdown or lost lease mid-send: no thread left sending, nothing sent unrecorded."""
    smtp.held.set()
    mailer = SmtpMailer(_settings())
    sending = asyncio.create_task(mailer.send("W", "Hi", key="k", ledger=ledger))
    assert await asyncio.to_thread(smtp.sending.wait, 5)  # Alice's copy is on its way

    sending.cancel()
    await asyncio.sleep(0.05)
    assert not sending.done()  # waits for the copy in flight
    smtp.release.set()
    with pytest.raises(asyncio.CancelledError):
        await sending

    smtp.held.clear()
    await mailer.send("W", "Hi", key="k", ledger=ledger)  # the run's next attempt

    first, retry = smtp.servers
    assert first.steps == [f"send {ALICE}"]  # stopped: no QUIT, and Bob's copy never started
    assert retry.steps == [f"send {BOB}", "quit"]  # Alice's was noted: she is not mailed again


async def test_a_stalled_copy_is_cut_off_at_the_timeout_and_sent_again(
    smtp: FakeSmtp, ledger: Steps
) -> None:
    """However slow the server, a copy ends by the timeout: it cannot outlast the lease."""
    mailer = SmtpMailer(_settings(timeout_seconds=0.1))
    smtp.stalled.add(BOB)

    started = time.monotonic()
    with pytest.raises(smtplib.SMTPServerDisconnected):
        await mailer.send("Weekly", "Hello world", key="report-1", ledger=ledger)
    cut_after = time.monotonic() - started
    smtp.stalled.clear()
    await mailer.send("Weekly", "Hello world", key="report-1", ledger=ledger)  # the retry

    assert 0.1 <= cut_after < 1
    assert (smtp.copies_to(ALICE), smtp.copies_to(BOB)) == (1, 1)  # Bob's cut copy was not noted


class StalledLedger:
    """A ledger whose database stops answering when a copy is to be noted."""

    async def recorded(self, prefix: str) -> frozenset[str]:  # noqa: ARG002  # nothing noted yet
        return frozenset()

    async def record(self, name: str) -> object:  # noqa: ARG002  # never answers
        await asyncio.Event().wait()
        return None


async def test_a_login_stalled_after_starttls_is_cut_at_the_timeout(
    smtp: FakeSmtp, ledger: Steps
) -> None:
    """STARTTLS replaces the socket object mid-step; the watchdog still cuts the connection."""
    smtp.stalled_login = True
    login = {"username": "infrasales", "password": SecretStr("pw"), "timeout_seconds": 0.2}
    settings = _settings("starttls", **login)
    started = time.monotonic()

    with pytest.raises(smtplib.SMTPServerDisconnected):
        await SmtpMailer(settings).send("W", "Hi", key="k", ledger=ledger)

    assert time.monotonic() - started < 1
    assert (smtp.servers[0].steps[0], smtp.accepted) == ("starttls", [])  # nothing sent


async def test_a_stalled_note_ends_the_session_by_the_copys_deadline(smtp: FakeSmtp) -> None:
    """The database stalls while noting a copy: the session ends within the SMTP timeout."""
    mailer = SmtpMailer(_settings(timeout_seconds=0.2))
    loop = asyncio.get_running_loop()
    started = loop.time()

    with pytest.raises(MailNotNotedError):
        await mailer.send("Weekly", "Hello world", key="k", ledger=StalledLedger())

    assert loop.time() - started < 1
    (server,) = smtp.servers
    assert server.steps == [f"send {ALICE}", "quit"]  # no further copy goes out unnoted


async def test_a_delivery_that_will_not_stop_holds_a_cancellation_no_longer_than_the_timeout(
    smtp: FakeSmtp, ledger: Steps
) -> None:
    """Even a server deaf to the cut connection cannot hold a shutdown or lost lease longer."""
    smtp.held.set()  # this copy ignores the cut: only `release` ends it
    sending = asyncio.create_task(
        SmtpMailer(_settings(timeout_seconds=0.2)).send("W", "Hi", key="k", ledger=ledger)
    )
    assert await asyncio.to_thread(smtp.sending.wait, 5)
    loop = asyncio.get_running_loop()
    cancelled_at = loop.time()

    sending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await sending
    waited = loop.time() - cancelled_at
    smtp.release.set()  # the stuck thread ends on its own, later
    await asyncio.sleep(0.1)

    assert 0.2 <= waited < 1


async def test_each_copy_is_built_in_the_thread_just_before_it_goes(
    smtp: FakeSmtp, ledger: Steps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No list of copies in memory, and no MIME work on the event loop."""
    built: list[tuple[bool, int]] = []  # (on the event loop's thread, copies sent before)

    class RecordedMessage(EmailMessage):
        def __init__(self) -> None:
            super().__init__()
            built.append(
                (threading.current_thread() is threading.main_thread(), len(smtp.accepted))
            )

    monkeypatch.setattr(mail_smtp, "EmailMessage", RecordedMessage)

    await SmtpMailer(_settings()).send("Weekly", "Hello world", key="k", ledger=ledger)

    assert built == [(False, 0), (False, 1)]


def test_one_session_mails_at_most_a_thousand_recipients() -> None:
    many = [f"reader{n}@example.org" for n in range(1001)]

    with pytest.raises(ValidationError, match="at most 1000"):
        _settings(recipients=many)


# A process cancelling its delivery while connecting stalls beyond every timeout: DNS, or a
# server whose greeting never ends.
_STALLED = """
import asyncio, contextlib, smtplib, socket, sys, threading
from infrasales.mail.settings import SmtpSettings
from infrasales.mail.smtp import SmtpMailer

def stall(*_):
    threading.Event().wait()

server = socket.create_server(("127.0.0.1", 0))  # accepts connections, never answers
if sys.argv[1] == "dns":
    socket.getaddrinfo = stall
else:
    smtplib.SMTP.getreply = stall

class Ledger:
    async def recorded(self, prefix):
        return frozenset()

async def main():
    settings = SmtpSettings(
        host="smtp.example.org" if sys.argv[1] == "dns" else "127.0.0.1",
        port=server.getsockname()[1],
        security="none",
        sender="infrasales@example.org",
        recipients=["alice@example.org"],
        timeout_seconds=0.1,
    )
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(0.1):  # e.g. a shutdown
            await SmtpMailer(settings).send("S", "B", key="k", ledger=Ledger())

asyncio.run(main())
"""


@pytest.mark.parametrize("stalled", ["dns", "server"])
def test_a_stalled_connection_attempt_never_holds_the_process(stalled: str) -> None:
    """The cancelled session's thread is abandoned at exit, not awaited: the process ends."""
    command = [sys.executable, "-c", _STALLED, stalled]

    subprocess.run(command, check=True, timeout=15)  # our interpreter and script
