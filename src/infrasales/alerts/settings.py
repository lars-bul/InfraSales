"""Who is told when a job fails, or keeps failing (`ALERTS__*`). Unset: nobody, logs only."""

from pydantic import BaseModel, Field, SecretStr

from infrasales.mail.settings import Addresses


class AlertSettings(BaseModel):
    # ALERTS__RECIPIENTS=ops@example.org: mailed through the SMTP server (SMTP__*)
    recipients: Addresses = Field(default_factory=list[str], max_length=100)
    # Slack, Mattermost, Rocket.Chat, Google Chat; its token is in the URL: a secret
    # (ALERTS__WEBHOOK_URL or /run/secrets/alerts__webhook_url)
    webhook_url: SecretStr | None = None
    # A run that is retried alerts once this many of its attempts failed; one that fails for
    # good always does. One failed attempt is no news: it is retried.
    after_failures: int = Field(default=2, ge=1)
