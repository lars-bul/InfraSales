import io
import json
import sys
import uuid

import pytest

from infrasales.core.db import Database
from infrasales.core.logs import configure_logging
from infrasales.mail.mailer import LogMailer, build_mailer
from infrasales.mail.settings import SmtpSettings
from infrasales.scheduler.steps import Steps


@pytest.mark.anyio
async def test_without_smtp_mail_is_logged() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    unused = Steps(Database("sqlite+aiosqlite://"), uuid.uuid7())  # nothing is delivered
    sent = await build_mailer(None).send("Subject", "Hello world", key="k-1", ledger=unused)

    assert sent == 0

    (line,) = [json.loads(raw) for raw in stream.getvalue().splitlines()]
    assert (line["event"], line["subject"], line["body"]) == (
        "mail not configured, not sent",
        "Subject",
        "Hello world",
    )


def test_with_smtp_the_smtp_mailer_is_loaded() -> None:
    settings = SmtpSettings(host="h", sender="r@x.org", recipients=["a@x.org"])

    mailer = build_mailer(settings)

    assert not isinstance(mailer, LogMailer)
    assert "infrasales.mail.smtp" in sys.modules
