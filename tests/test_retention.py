import asyncio
import contextlib
import io
import json
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable
from datetime import timedelta
from typing import Any, NoReturn, cast

import pytest
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales import retention
from infrasales.audit import service as audit_service
from infrasales.audit.models import AuditEvent
from infrasales.auth.models import AuthSession, Role
from infrasales.core.db import Database
from infrasales.core.logs import configure_logging
from infrasales.core.models import utcnow
from infrasales.scheduler.models import JobRun, JobStatus, JobStep, JobTrigger
from infrasales.scheduler.steps import Steps
from infrasales.settings import RetentionSettings
from tests.helpers import fill, postgres_only, query_plan
from tests.scrape.support import memory_sink

pytestmark = pytest.mark.anyio
DAY = timedelta(days=1)


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


def _session(name: str, *, last_seen: timedelta, expires: timedelta) -> AuthSession:
    now = utcnow()
    return AuthSession(
        token_hash=name.ljust(64, "0"),
        subject=f"basic:{name}",
        name=name,
        role=Role.VIEWER,
        last_seen_at=now - last_seen,
        expires_at=now + expires,
    )


def _run(name: str, status: JobStatus, *, age: timedelta, finished: timedelta | None) -> JobRun:
    now = utcnow()
    return JobRun(
        job=name,
        status=status,
        scheduled_for=now - age,
        run_after=now - age,
        created_at=now - age,
        finished_at=None if finished is None else now - finished,
    )


async def test_expired_rows_are_deleted_and_the_pruning_is_audited(db: Database) -> None:
    now = utcnow()
    async with db.session() as session:
        session.add_all(
            [
                AuditEvent(action="old", created_at=now - 181 * DAY),
                AuditEvent(action="kept", created_at=now - 179 * DAY),
                _run("old", JobStatus.SUCCEEDED, age=95 * DAY, finished=91 * DAY),
                _run("old failure", JobStatus.FAILED, age=95 * DAY, finished=91 * DAY),
                _run("finished lately", JobStatus.FAILED, age=95 * DAY, finished=89 * DAY),
                _session("expired", last_seen=timedelta(0), expires=-DAY),
                _session("idle", last_seen=timedelta(hours=9), expires=DAY),
                _session("active", last_seen=timedelta(minutes=5), expires=DAY),
            ]
        )

    deleted = await retention.prune(db, memory_sink(), RetentionSettings(), now)

    jobs = [run.job for run in await _all(db, JobRun)]
    names = [session.name for session in await _all(db, AuthSession)]
    events = await _all(db, AuditEvent)
    assert deleted == {
        "audit_event": 1,
        "job_run": 2,
        "auth_session": 2,
        "source_version": 0,  # tests/test_retention_versions.py
        "source": 0,
        "sink_folder": 0,
    }
    assert (jobs, names) == (["finished lately"], ["active"])  # kept by when it finished
    assert _deletions(events) == {table: n for table, n in deleted.items() if n}  # each batch
    (pruned,) = [event for event in events if event.action == "retention.pruned"]
    assert (pruned.actor, pruned.details) == (None, deleted)  # and the round
    assert sorted(e.action for e in events if not e.action.startswith("retention.")) == ["kept"]


async def test_deletions_are_audited_even_if_the_round_fails_halfway(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every committed deletion has its audit record: it is written in the same transaction."""
    now = utcnow()
    async with db.session() as session:
        session.add_all(AuditEvent(action="old", created_at=now - 181 * DAY) for _ in range(3))
    record = audit_service.record

    def failing_after_deleting(session: AsyncSession, **fields: Any) -> None:  # noqa: ANN401  # passed through
        if fields["action"] == "retention.pruned":  # the round's summary, after the deletions
            raise ConnectionError
        record(session, **fields)

    monkeypatch.setattr(audit_service, "record", failing_after_deleting)

    with pytest.raises(ConnectionError):
        await retention.prune(db, memory_sink(), RetentionSettings(), now)

    events = await _all(db, AuditEvent)
    assert not [event for event in events if event.action == "old"]  # deleted, irreversibly
    assert _deletions(events) == {"audit_event": 3}  # yet accounted for


async def test_unfinished_runs_keep_their_steps_finished_ones_lose_them(db: Database) -> None:
    """After a long outage, a queued run still has its report and who received it.

    The "Run now" requests that a run answered go with it too: their keys answer it as long
    as it is kept.
    """
    queued = _run("queued", JobStatus.PENDING, age=400 * DAY, finished=None)
    abandoned = _run("abandoned", JobStatus.RUNNING, age=400 * DAY, finished=None)
    done = _run("done", JobStatus.SUCCEEDED, age=400 * DAY, finished=399 * DAY)
    async with db.session() as session:
        session.add_all([queued, abandoned, done])
        session.add_all(
            JobTrigger(job=run.job, key=uuid.uuid4(), run_id=run.id) for run in (queued, done)
        )
    for run in (queued, done):
        steps = Steps(db, run.id)
        await steps.record("write", "Hello world")
        await steps.record("report-1 3f2a")  # a recipient already mailed

    deleted = await retention.prune(db, memory_sink(), RetentionSettings(), utcnow())

    assert deleted["job_run"] == 1
    assert {run.job for run in await _all(db, JobRun)} == {"queued", "abandoned"}
    assert {step.run_id for step in await _all(db, JobStep)} == {queued.id}
    assert {trigger.run_id for trigger in await _all(db, JobTrigger)} == {queued.id}
    assert await Steps(db, queued.id).recorded("report-1 ") == {"report-1 3f2a"}


@pytest.mark.parametrize("expired", [5, 4])  # a last partial batch, and an exact multiple
async def test_large_backlogs_are_pruned_in_batches(
    db: Database, monkeypatch: pytest.MonkeyPatch, expired: int
) -> None:
    monkeypatch.setattr(retention, "_BATCH", 2)
    now = utcnow()
    async with db.session() as session:
        session.add_all(
            AuditEvent(action="old", created_at=now - 181 * DAY) for _ in range(expired)
        )

    deleted = await retention.prune(db, memory_sink(), RetentionSettings(), now)

    batches = [e.details["rows"] for e in await _all(db, AuditEvent) if e.target == "audit_event"]
    assert deleted["audit_event"] == expired
    assert batches == ([2, 2, 1] if expired == 5 else [2, 2])  # one audit event per batch


AUDIT_EVENTS = (  # 100,000 events, 1,000 of them past retention
    "INSERT INTO audit_event (id, created_at, updated_at, action, outcome, details)"
    " SELECT gen_random_uuid(), now() - (CASE WHEN g <= 1000 THEN 200 ELSE 1 END)"
    " * interval '1 day', now(), 'test', 'success', '{}' FROM generate_series(1, 100000) AS g"
)
SESSIONS = (  # 100,000 sessions, 1,000 of them idle too long
    "INSERT INTO auth_session (id, created_at, updated_at, token_hash, subject, name, role,"
    " last_seen_at, expires_at) SELECT gen_random_uuid(), now(), now(), md5(g::text),"
    " 'basic:u' || g, 'u', 'viewer', now() - (CASE WHEN g <= 1000 THEN 30 ELSE 0 END)"
    " * interval '1 hour', now() + interval '1 day' FROM generate_series(1, 100000) AS g"
)


@postgres_only
@pytest.mark.parametrize(
    ("rows", "candidates", "deletion"),
    [
        (AUDIT_EVENTS, "SELECT audit_event.id", "DELETE FROM audit_event"),
        (SESSIONS, "SELECT auth_session.id", "DELETE FROM auth_session"),
    ],
)
async def test_pruning_finds_and_deletes_expired_rows_by_index(
    db: Database, rows: str, candidates: str, deletion: str
) -> None:
    await fill(db, rows)

    def prune() -> Awaitable[dict[str, int]]:
        return retention.prune(db, memory_sink(), RetentionSettings(), utcnow())

    plan = await query_plan(db, prune, candidates, deletion)

    assert "Seq Scan" not in plan, plan


def _deletions(events: list[AuditEvent]) -> dict[str, int]:
    """Rows deleted per table, as the audit trail accounts for them."""
    counted = Counter[str]()
    for event in events:
        if event.action == "retention.deleted" and event.target:
            counted[event.target] += cast("int", event.details["rows"])
    return dict(counted)


async def _all[T: SQLModel](db: Database, table: type[T]) -> list[T]:
    async with db.session() as session:
        return list((await session.exec(select(table))).all())


async def test_a_single_run_prunes_once(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    rounds: list[object] = []

    async def prune(*args: object) -> dict[str, int]:
        rounds.append(args)
        return {}

    monkeypatch.setattr(retention, "prune", prune)

    await retention.run(db, memory_sink(), RetentionSettings(), every=None)

    assert len(rounds) == 1


async def test_as_a_service_it_prunes_repeatedly_until_stopped(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    rounds, third_round = 0, asyncio.Event()

    async def prune(*_: object) -> dict[str, int]:
        nonlocal rounds
        rounds += 1
        if rounds == 1:
            raise ConnectionError  # a failed round does not end the service
        if rounds == 3:
            third_round.set()
        return {}

    monkeypatch.setattr(retention, "prune", prune)
    monkeypatch.setattr(retention, "stop_requested", third_round.wait)

    async with asyncio.timeout(5):
        await retention.run(db, memory_sink(), RetentionSettings(), timedelta(0))

    events = [json.loads(line)["event"] for line in stream.getvalue().splitlines()]
    assert rounds >= 3
    assert "retention.failed" in events


async def test_a_round_cut_off_mid_query_ends_with_the_service(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its cancellation surfaces as an error, which rounds are retried on: it stops all the same.

    Or it would sleep until the next round, a day, while shutdown waits for it.
    """
    stream, started = io.StringIO(), asyncio.Event()
    configure_logging(stream=stream)

    async def cut_off(*_: object) -> NoReturn:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise ConnectionError from None  # as psycopg now and then does
        raise AssertionError  # never answers

    monkeypatch.setattr(retention, "prune", cut_off)
    monkeypatch.setattr(retention, "stop_requested", started.wait)

    async with asyncio.timeout(5):
        await retention.run(db, memory_sink(), RetentionSettings(), timedelta(days=1))

    assert "retention.failed" not in stream.getvalue()  # stopped, not a round to retry
    assert "retention.stop_timed_out" not in stream.getvalue()


async def test_a_round_that_will_not_stop_is_left_behind(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream, started = io.StringIO(), asyncio.Event()
    configure_logging(stream=stream)

    async def stubborn(*_: object) -> NoReturn:
        started.set()
        with contextlib.suppress(asyncio.CancelledError):  # ignores the stop
            await asyncio.Event().wait()
        await asyncio.Event().wait()  # until the test's event loop ends
        raise AssertionError

    monkeypatch.setattr(retention, "prune", stubborn)
    monkeypatch.setattr(retention, "stop_requested", started.wait)
    monkeypatch.setattr(retention, "_STOP_SECONDS", 0.1)

    async with asyncio.timeout(5):
        await retention.run(db, memory_sink(), RetentionSettings(), timedelta(days=1))

    assert "retention.stop_timed_out" in stream.getvalue()
