import pytest

from infrasales.audit.models import AuditEvent, Outcome
from infrasales.core.db import Database
from infrasales.core.models import JSONValue
from tests.helpers import audit_events

pytestmark = pytest.mark.anyio


async def test_events_keep_structured_details(database_url: str) -> None:
    db = Database(database_url)
    details: dict[str, JSONValue] = {"after": {"days": ["mon"], "enabled": True}, "count": 2}
    async with db.session() as session:
        session.add(AuditEvent(action="config.updated", details=details))
    await db.dispose()

    (stored,) = await audit_events(database_url)

    assert stored.details == details
    assert stored.outcome is Outcome.SUCCESS
    assert stored.actor is None
