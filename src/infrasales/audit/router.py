from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlmodel import col, select
from sqlmodel.sql.expression import SelectOfScalar

from infrasales.audit import service
from infrasales.audit.models import AuditEvent
from infrasales.audit.schemas import AuditEventRead, AuditQuery
from infrasales.auth.deps import AdminUser
from infrasales.core.db import Session

router = APIRouter(prefix="/api/audit-events", tags=["audit"])


@router.get("")
async def list_audit_events(
    query: Annotated[AuditQuery, Query()], request: Request, admin: AdminUser, session: Session
) -> list[AuditEventRead]:
    """Audit events, newest first; reading them is itself audited: they are personal data."""
    events = (await session.exec(_matching(query))).all()
    asked = query.model_dump(mode="json", exclude={"limit"}, exclude_none=True)
    service.record(
        session, actor=admin.subject, action="audit.read", details=asked or None, request=request
    )
    return [AuditEventRead.model_validate(event, from_attributes=True) for event in events]


def _matching(query: AuditQuery) -> SelectOfScalar[AuditEvent]:
    statement = select(AuditEvent)
    if query.before:
        statement = statement.where(col(AuditEvent.id) < query.before)
    if query.action:
        statement = statement.where(col(AuditEvent.action) == query.action)
    if query.actor:
        statement = statement.where(col(AuditEvent.actor) == query.actor)
    return statement.order_by(col(AuditEvent.id).desc()).limit(query.limit)
