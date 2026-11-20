import pytest
from pydantic import ValidationError

from infrasales.mail.settings import SmtpSettings, mailbox
from infrasales.settings import WorkerSettings


@pytest.fixture(autouse=True)
def _database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")


def test_without_a_host_no_mail_is_sent() -> None:
    assert WorkerSettings.load().smtp is None


def test_smtp_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP__HOST", "smtp.example.org")
    monkeypatch.setenv("SMTP__SENDER", "infrasales@example.org")
    monkeypatch.setenv("SMTP__RECIPIENTS", "a@example.org, b@example.org")

    smtp = WorkerSettings.load().smtp

    assert smtp
    assert (smtp.port, smtp.security) == (587, "starttls")  # encrypted unless chosen otherwise
    assert smtp.recipients == ["a@example.org", "b@example.org"]


@pytest.mark.parametrize(
    "invalid", [{"recipients": []}, {"recipients": "not-an-address"}, {"security": "ssl"}]
)
def test_invalid_mail_settings_are_rejected(invalid: dict[str, object]) -> None:
    valid: dict[str, object] = {"host": "h", "sender": "r@x.org", "recipients": ["a@x.org"]}

    with pytest.raises(ValidationError):
        SmtpSettings.model_validate(valid | invalid)


def test_each_mailbox_is_a_recipient_once() -> None:
    settings = SmtpSettings.model_validate(
        {"host": "h", "sender": "r@x.org", "recipients": "Ann@X.org, b@x.org, ann@x.org , B@X.ORG"}
    )

    assert settings.recipients == ["Ann@X.org", "b@x.org"]  # each first spelling
    assert mailbox(" Ann@X.org") == mailbox("ann@x.org") == "ann@x.org"
