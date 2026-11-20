import pytest
from pydantic import SecretStr, ValidationError

from infrasales.alerts.settings import AlertSettings


def test_by_default_nobody_is_alerted() -> None:
    alerts = AlertSettings()

    assert (alerts.recipients, alerts.webhook_url, alerts.after_failures) == ([], None, 2)


def test_recipients_are_addresses_each_mailbox_once() -> None:
    alerts = AlertSettings.model_validate({"recipients": "ops@x.org, OPS@x.org ,dev@x.org"})

    assert alerts.recipients == ["ops@x.org", "dev@x.org"]
    with pytest.raises(ValidationError, match="not e-mail addresses"):
        AlertSettings.model_validate({"recipients": "ops"})


def test_the_webhook_url_holds_a_token_and_stays_secret() -> None:
    alerts = AlertSettings(webhook_url=SecretStr("https://hooks.test/T0KEN"))

    assert "T0KEN" not in repr(alerts)
