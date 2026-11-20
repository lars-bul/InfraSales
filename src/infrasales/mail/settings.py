"""Outgoing mail (`SMTP__*`). Without `SMTP__HOST` nothing is sent: mail is logged instead."""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, SecretStr

from infrasales.core.fields import CommaSeparated

ADDRESS = r"^[^@\s]+@[^@\s]+$"


def mailbox(address: str) -> str:
    """Who an address reaches: addresses differing only in case or spacing are one mailbox."""
    return address.strip().lower()


def _addresses(values: list[str]) -> list[str]:
    """Valid addresses, each mailbox once (its first spelling): nobody gets a mail twice."""
    if invalid := [value for value in values if not re.fullmatch(ADDRESS, value.strip())]:
        msg = f"not e-mail addresses: {invalid}"
        raise ValueError(msg)
    unique: dict[str, str] = {}
    for value in values:
        unique.setdefault(mailbox(value), value.strip())
    return list(unique.values())


# `A=a@x.org, b@x.org`: valid addresses, each mailbox once
Addresses = Annotated[CommaSeparated, AfterValidator(_addresses)]


class SmtpSettings(BaseModel):
    host: str = Field(min_length=1)
    port: int = Field(default=587, gt=0, lt=65536)
    # starttls (port 587) or tls (implicit, port 465) verify the server certificate;
    # none sends in plain text: only for a local mail catcher.
    security: Literal["starttls", "tls", "none"] = "starttls"
    username: str | None = None  # log in only when set
    password: SecretStr | None = None  # SMTP__PASSWORD or /run/secrets/smtp__password
    sender: str = Field(pattern=ADDRESS)
    # SMTP__RECIPIENTS=a@example.org,b@example.org. One session mails them one after
    # another: a larger audience belongs on a mailing list's address.
    recipients: Addresses = Field(min_length=1, max_length=1000)
    # The longest a connection step or one copy may take: a copy taking longer is cut off.
    # Below the scheduler's stop margin, so no copy is in flight when a run changes workers.
    timeout_seconds: float = Field(default=10, gt=0)
