import io

import pytest

from infrasales.alerts.mail import MailNotifier
from infrasales.core.logs import configure_logging
from infrasales.mail.settings import SmtpSettings
from tests.alerts.support import FAILED, RUN
from tests.mail.support import FakeSmtp

pytestmark = pytest.mark.anyio


async def test_an_alert_is_mailed_to_the_alert_recipients_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_logging(stream=io.StringIO())
    smtp = FakeSmtp.installed(monkeypatch)
    report = SmtpSettings(
        host="smtp.test", security="none", sender="infrasales@x.org", recipients=["readers@x.org"]
    )
    notifier = MailNotifier(report, ["ops@x.org", "dev@x.org"])

    await notifier.notify(FAILED)
    await notifier.notify(FAILED)  # not resumed from notes: each alert goes out whole

    sent = [message for server in smtp.servers for message in server.sent]
    assert [str(message["To"]) for message in sent] == ["ops@x.org", "dev@x.org"] * 2
    assert sent[0]["Subject"] == "infrasales: report failed"
    assert sent[0]["Message-ID"] == f"<alert-{RUN}-3@x.org>"
    assert sent[0].get_content().strip() == FAILED.text()
