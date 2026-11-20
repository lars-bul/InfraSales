import io
import json
from dataclasses import replace

import pytest
from pydantic import SecretStr

from infrasales.alerts.notifier import Alerting, build_notifier
from infrasales.alerts.settings import AlertSettings
from infrasales.config.schemas import ConfigKey
from infrasales.core.db import Database
from infrasales.core.logs import configure_logging
from infrasales.core.models import JSONValue
from infrasales.mail.settings import SmtpSettings
from infrasales.scheduler.registry import JobContext, ScheduledJob
from infrasales.scheduler.worker import Worker
from tests.alerts.support import FAILED, RecordingNotifier
from tests.mail.support import FakeSmtp
from tests.scheduler.support import FAST, Clock, stored_runs

pytestmark = pytest.mark.anyio
SMTP = SmtpSettings(
    host="smtp.test", security="none", sender="infrasales@x.org", recipients=["readers@x.org"]
)


@pytest.mark.parametrize(
    ("outcome", "attempt", "told"),
    [("retrying", 1, False), ("retrying", 2, True), ("failed", 1, True)],
)
async def test_one_failed_attempt_is_no_news_a_run_failing_again_is(
    outcome: str, attempt: int, *, told: bool
) -> None:
    channel = RecordingNotifier()
    alert = replace(FAILED, outcome=outcome, attempt=attempt)

    await Alerting([channel], after_failures=2).notify(alert)

    assert bool(channel.alerts) is told


async def test_a_failing_channel_does_not_silence_the_others() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    broken, working = RecordingNotifier(error=ConnectionError()), RecordingNotifier()

    await Alerting([broken, working], after_failures=2).notify(FAILED)

    assert working.alerts == [FAILED]
    (line,) = [json.loads(raw) for raw in stream.getvalue().splitlines()]
    assert (line["event"], line["channel"]) == ("alert.not_sent", "RecordingNotifier")


@pytest.mark.parametrize(
    ("alerts", "channels"),
    [
        ({}, None),
        ({"recipients": ["ops@x.org"]}, ["MailNotifier"]),
        ({"webhook_url": SecretStr("https://hooks.test/T")}, ["WebhookNotifier"]),
        (
            {"recipients": ["ops@x.org"], "webhook_url": SecretStr("https://hooks.test/T")},
            ["MailNotifier", "WebhookNotifier"],
        ),
    ],
)
def test_each_configured_channel_is_told(
    alerts: dict[str, object], channels: list[str] | None
) -> None:
    notifier = build_notifier(AlertSettings.model_validate(alerts), SMTP)

    if channels is None:
        assert notifier is None
    else:
        assert isinstance(notifier, Alerting)
        assert [type(channel).__name__ for channel in notifier.channels] == channels


async def test_a_run_failing_for_good_is_mailed_to_the_alert_recipients(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: the worker, the alert policy and the mail channel on an SMTP fake."""
    configure_logging(stream=io.StringIO())
    smtp = FakeSmtp.installed(monkeypatch)
    alerts = build_notifier(AlertSettings(recipients=["ops@x.org"]), SMTP)

    async def failing(_: JobContext) -> JSONValue:
        raise TimeoutError

    registry = {
        "scrape": ScheduledJob(run=failing, schedule=ConfigKey.SCRAPE_SCHEDULE, notifier=alerts)
    }
    db = Database(database_url)
    await Worker(db, registry, FAST.model_copy(update={"max_attempts": 1}), Clock()).tick()
    (run,) = await stored_runs(db)
    await db.dispose()

    (message,) = [message for server in smtp.servers for message in server.sent]
    assert (message["To"], message["Subject"]) == ("ops@x.org", "infrasales: scrape failed")
    assert message.get_content().strip() == (
        f"The job scrape failed for good: attempt 1 of 1 raised TimeoutError.\nRun: {run.id}"
    )
