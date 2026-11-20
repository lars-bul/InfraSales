"""Recording audit events, in the caller's transaction: no change commits without its event."""

import ipaddress
from collections.abc import Mapping

import structlog
from fastapi import Request
from sqlalchemy import event
from sqlalchemy.orm import Session as SyncSession
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.audit.models import AuditEvent, Outcome
from infrasales.core.models import JSONValue

_log = structlog.stdlib.get_logger(__name__)


def client_network(host: str | None) -> str | None:
    """The client's network (/24 for IPv4, /48 for IPv6): enough to spot abuse, not a person."""
    try:
        address = ipaddress.ip_address((host or "").partition("%")[0])
    except ValueError:
        return None
    prefix = 24 if address.version == 4 else 48  # noqa: PLR2004
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))


def record(  # noqa: PLR0913  # one keyword per audit field
    session: AsyncSession,
    *,
    actor: str | None,
    action: str,
    outcome: Outcome = Outcome.SUCCESS,
    target: str | None = None,
    details: Mapping[str, JSONValue] | None = None,
    request: Request | None = None,
) -> None:
    """Add an audit event to the transaction; a copy goes to the log once it commits.

    The log copy lets log storage outside the database witness the trail.
    """
    audit_event = AuditEvent(
        actor=actor,
        action=action,
        outcome=outcome,
        target=target,
        details=dict(details or {}),
        client_network=client_network(request.client.host if request and request.client else None),
    )
    session.add(audit_event)

    def log_copy(_: SyncSession) -> None:
        _log.info("audit", **audit_event.model_dump(mode="json", exclude={"client_network"}))

    event.listen(session.sync_session, "after_commit", log_copy, once=True)
