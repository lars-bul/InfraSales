import io
import json

import pytest
from starlette.requests import Request

from infrasales.audit.models import Outcome
from infrasales.audit.service import client_network, record
from infrasales.core.db import Database
from infrasales.core.logs import configure_logging
from tests.helpers import audit_events

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("host", "network"),
    [
        ("203.0.113.77", "203.0.113.0/24"),
        ("2001:db8:abcd:12::1", "2001:db8:abcd::/48"),
        ("fe80::1%eth0", "fe80::/48"),
        ("testclient", None),
        (None, None),
    ],
)
def test_only_the_client_network_is_kept(host: str | None, network: str | None) -> None:
    assert client_network(host) == network


async def test_events_are_recorded_and_logged_once_committed(database_url: str) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    db = Database(database_url)
    request = Request({"type": "http", "client": ("203.0.113.77", 4711)})

    async with db.session() as session:
        record(
            session,
            actor="basic:alice",
            action="config.updated",
            target="report_schedule",
            details={"enabled": False},
            request=request,
        )
        logged_before_commit = stream.getvalue()
    await db.dispose()

    (stored,) = await audit_events(database_url)
    (logged,) = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert logged_before_commit == ""
    assert (stored.actor, stored.client_network) == ("basic:alice", "203.0.113.0/24")
    assert logged["event"] == "audit"
    assert (logged["action"], logged["target"]) == ("config.updated", "report_schedule")
    assert "client_network" not in logged


async def _record_then_fail(db: Database) -> None:
    async with db.session() as session:
        record(session, actor=None, action="system.check", outcome=Outcome.FAILURE)
        raise RuntimeError


async def test_rolled_back_events_are_neither_stored_nor_logged(database_url: str) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    db = Database(database_url)

    with pytest.raises(RuntimeError):
        await _record_then_fail(db)
    await db.dispose()

    assert await audit_events(database_url) == []
    assert stream.getvalue() == ""
