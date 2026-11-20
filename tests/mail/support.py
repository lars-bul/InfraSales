"""A fake SMTP server for tests: records what the mailer does, and misbehaves on request."""

import select
import smtplib
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Self

import pytest


def _cut_within(connection: socket.socket, seconds: float) -> bool:
    """Whether the connection is cut within `seconds`: a cut connection reads as ended."""
    readable, _, _ = select.select([connection], [], [], seconds)
    return bool(readable)


class FakeServer:
    """Stands in for smtplib.SMTP and SMTP_SSL, behaving as its `FakeSmtp` says.

    Its connection is a real socket, which the mailer's watchdog cuts, and STARTTLS replaces
    the socket object the way `ssl` does: the old one is detached, the connection stays.
    """

    def __init__(
        self,
        smtp: FakeSmtp,
        address: tuple[str, int],
        timeout: float,
        context: ssl.SSLContext | None,
    ) -> None:
        self.smtp, self.address, self.timeout = smtp, address, timeout
        self.implicit_tls = context is not None
        self.sock: socket.socket | None
        self.sock, self._server = socket.socketpair()  # the server never writes: reads wait
        self.steps: list[str] = []
        self.sent: list[EmailMessage] = []

    def _connection(self) -> socket.socket:
        assert self.sock, "used after close"
        return self.sock

    def quit(self) -> None:
        self.steps.append("quit")

    def close(self) -> None:
        self._connection().close()
        self._server.close()
        self.sock = None

    def starttls(self, *, context: ssl.SSLContext) -> None:
        assert context.verify_mode is ssl.CERT_REQUIRED
        assert context.check_hostname
        self.steps.append("starttls")
        self.sock = socket.socket(fileno=self._connection().detach())

    def login(self, user: str, password: str) -> None:
        if self.smtp.stalled_login:  # only a cut connection ends it
            assert _cut_within(self._connection(), 5)
            raise smtplib.SMTPServerDisconnected
        self.steps.append(f"login {user}:{password}")

    def send_message(self, message: EmailMessage) -> None:
        smtp, to = self.smtp, str(message["To"])
        if to in smtp.failing:
            raise smtp.failing[to]
        if to in smtp.stalled:  # only a cut connection ends this copy
            assert _cut_within(self._connection(), 5)
            raise smtplib.SMTPServerDisconnected
        if smtp.held.is_set():  # the copy takes until the test releases it
            smtp.sending.set()
            assert smtp.release.wait(5)
        if _cut_within(self._connection(), smtp.copy_seconds):  # cut before it was accepted
            raise smtplib.SMTPServerDisconnected
        self.sent.append(message)
        self.steps.append(f"send {to}")
        smtp.accepted.append((to, time.monotonic()))


@dataclass
class FakeSmtp:
    """smtplib's servers, replaced: what the mailer did, and how the servers behave."""

    servers: list[FakeServer] = field(default_factory=list[FakeServer])
    accepted: list[tuple[str, float]] = field(default_factory=list[tuple[str, float]])  # when
    failing: dict[str, Exception] = field(default_factory=dict[str, Exception])
    stalled: set[str] = field(default_factory=set[str])
    stalled_login: bool = False
    copy_seconds: float = 0
    held: threading.Event = field(default_factory=threading.Event)
    sending: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    @classmethod
    def installed(cls, monkeypatch: pytest.MonkeyPatch) -> Self:
        smtp = cls()
        monkeypatch.setattr(smtplib, "SMTP", smtp.open)
        monkeypatch.setattr(smtplib, "SMTP_SSL", smtp.open)
        return smtp

    def open(
        self, host: str, port: int, *, timeout: float, context: ssl.SSLContext | None = None
    ) -> FakeServer:
        server = FakeServer(self, (host, port), timeout, context)
        self.servers.append(server)
        return server

    def copies_to(self, address: str) -> int:
        return [to for to, _ in self.accepted].count(address)
