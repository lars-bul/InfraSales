"""Retention: delete what has outlived its purpose.

Runs as its own process with its own database role (`infrasales prune`): once, from a scheduler
such as a Kubernetes CronJob, or as a service with `--every 24h` (the compose stack).
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import ColumnElement, exists, func, or_
from sqlalchemy.orm import aliased
from sqlmodel import col, delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.audit import service as audit
from infrasales.audit.models import AuditEvent
from infrasales.auth.models import AuthSession
from infrasales.auth.sessions import TIMEOUTS
from infrasales.catalog import versions
from infrasales.catalog.models import Source, SourceVersion, VersionState
from infrasales.core.db import Database
from infrasales.core.models import BaseTable, utcnow
from infrasales.core.signals import stop_requested
from infrasales.core.tasks import raise_if_cancelled
from infrasales.scheduler.models import JobRun, JobStatus
from infrasales.settings import RetentionSettings
from infrasales.sink.store import Sink

_log = structlog.stdlib.get_logger(__name__)


_BATCH = 1000
_FINISHED = (JobStatus.SUCCEEDED, JobStatus.FAILED)
_STOP_SECONDS = 10


async def _prune(db: Database, table: type[BaseTable], *expired: ColumnElement[bool]) -> int:
    """Delete the rows matching `expired`, a batch per transaction; return how many.

    Each batch is audited in its own transaction: no deletion commits without its record,
    however a round ends.
    """
    deleted, name = 0, table.table_name()
    while True:
        async with db.session() as session:
            # Two statements, each by index: `id IN (subquery)` would have PostgreSQL scan the
            # whole table to join the batch back.
            batch = (await session.exec(select(table.id).where(*expired).limit(_BATCH))).all()
            if not batch:
                return deleted
            count = (await session.exec(delete(table).where(col(table.id).in_(batch)))).rowcount
            details = {"rows": count}
            audit.record(
                session, actor=None, action="retention.deleted", target=name, details=details
            )
        deleted += count
        if len(batch) < _BATCH:
            return deleted


@dataclass
class _Tally:
    """What a round deleted of the catalog: versions, and Sources left without any."""

    versions: int = 0
    sources: int = 0


def _expired_versions(
    period: timedelta, now: datetime
) -> tuple[list[ColumnElement[bool]], list[ColumnElement[bool]]]:
    """Which committed versions have expired (ADR 03 §8): the replaced ones, the current ones.

    A version expires `RETENTION__SOURCE_DAYS` after it stopped being current: a replaced one
    after `superseded_at`, the current one after its Source was last checked (a page each run
    confirms keeps its text). `retain_until` keeps a version longer.

    The current version goes only as its Source's last: while an older one is kept (its
    `retain_until`) or a run is writing a new one, the latest pointer keeps naming the highest
    committed version.
    """
    cutoff = now - period
    kept = or_(col(SourceVersion.retain_until).is_(None), col(SourceVersion.retain_until) <= now)
    replaced = [col(SourceVersion.superseded_at) < cutoff, kept]
    other = aliased(SourceVersion)
    current = [
        col(SourceVersion.superseded_at).is_(None),
        kept,
        exists().where(
            col(Source.latest_version_id) == col(SourceVersion.id),
            col(Source.last_checked_at) < cutoff,
        ),
        ~exists().where(
            col(other.source_id) == col(SourceVersion.source_id),
            col(other.id) != col(SourceVersion.id),
        ),
    ]
    return replaced, current


async def _prune_versions(
    db: Database, sink: Sink, tally: _Tally, *expired: ColumnElement[bool]
) -> None:
    """Delete the committed versions matching `expired`, folders and rows, batch by batch.

    A batch is marked `deleted` in one transaction with its audit record: from then on no
    reader trusts it. Its folders and rows go next, by the catalog's one way of deleting a
    version (which also deletes a Source left without versions; audited after them). A round
    cut off in between leaves `deleted` versions, which the next one completes.
    """
    committed = col(SourceVersion.state) == VersionState.COMMITTED
    while True:
        async with db.session() as session:
            candidates = select(SourceVersion.id, SourceVersion.source_id).where(
                committed, *expired
            )
            batch = (await session.exec(candidates.limit(_BATCH))).all()
            if not batch:
                return
            # Their Sources first, as a commit does: a run checking or committing one of them
            # meanwhile either came first (its version is no longer expired) or waits.
            sources = sorted({source_id for _, source_id in batch})
            await session.exec(
                select(Source.id)
                .where(col(Source.id).in_(sources))
                .order_by(col(Source.id))
                .with_for_update()
            )
            marked = await session.exec(
                update(SourceVersion)
                .where(col(SourceVersion.id).in_([id_ for id_, _ in batch]), committed, *expired)
                .values(state=VersionState.DELETED)
                .returning(col(SourceVersion.id), col(SourceVersion.source_id))
            )
            deleting = list(marked.tuples())
            _audit_deleted(session, SourceVersion, len(deleting))
        for version_id, _ in deleting:
            await versions.delete_version(db, sink, version_id)
        tally.versions += len(deleting)
        tally.sources += await _sources_gone(db, {source_id for _, source_id in deleting})
        if len(batch) < _BATCH:
            return


async def _sources_gone(db: Database, sources: set[uuid.UUID]) -> int:
    """How many of `sources` were deleted (left without versions); audited."""
    if not sources:
        return 0
    async with db.session() as session:
        left = select(func.count()).select_from(Source).where(col(Source.id).in_(sources))
        gone = len(sources) - (await session.exec(left)).one()
        if gone:
            _audit_deleted(session, Source, gone)
    return gone


async def _complete_deletions(db: Database, sink: Sink, tally: _Tally) -> None:
    """Complete the deletions a crash cut off: versions left `deleted`.

    They were accounted for when marked (or never committed: the scrape's leftovers); the
    Sources they leave empty are counted now.
    """
    tally.sources += await _sources_gone(db, set(await versions.finish_deletions(db, sink)))


async def _prune_orphans(db: Database, sink: Sink) -> int:
    """Delete the version folders no catalog row names (`storage_key`); how many.

    A version's row is written before its folder and deleted after it, so a folder without a
    row is left over: by a scrape attempt that froze past its lease, was swept and wrote on
    (and crashed before it could discard its files). Readers never trust such a folder (only
    committed rows); deleting it frees its space and leaves no copy without a record (P2).

    The sink is listed before the rows are read: a version started in between is read too.
    Every file of the sink is listed: once a day, a few hundred thousand keys at most.
    """
    folders: set[str] = set()
    for key in await sink.list():
        *folder, _ = key.split("/")
        if len(folder) == _VERSION_FOLDER_DEPTH and _is_uuid(folder[-1]):
            folders.add("/".join(folder))
    async with db.session() as session:
        named = set((await session.exec(select(SourceVersion.storage_key))).all())
    orphans = sorted(folders - named)
    for folder in orphans:
        await sink.delete(folder)
    if orphans:
        async with db.session() as session:
            details = {"folders": len(orphans)}
            audit.record(
                session,
                actor=None,
                action="retention.deleted",
                target="sink_folder",
                details=details,
            )
    return len(orphans)


_VERSION_FOLDER_DEPTH = 3  # <run>/<feed slug>/<source version id> (`infrasales.catalog.layout`)


def _is_uuid(name: str) -> bool:
    try:
        uuid.UUID(name)
    except ValueError:
        return False
    return True


def _audit_deleted(session: AsyncSession, table: type[BaseTable], rows: int) -> None:
    details = {"rows": rows}
    target = table.table_name()
    audit.record(session, actor=None, action="retention.deleted", target=target, details=details)


async def prune(
    db: Database, sink: Sink, settings: RetentionSettings, now: datetime
) -> dict[str, int]:
    """Delete expired rows and audit them, batch by batch, then the round; return the counts.

    Job runs are history once finished: pending and running runs are work, never pruned. A
    run's steps (a mail it wrote, who received it) are deleted with it. Source Versions are kept
    for good unless a period is set (ADR 06 §7); with one, they go with their files in the sink,
    and Sources left without versions with them. Folders in the sink that no version names go
    too (`sink_folder`).
    """
    longest_idle = max(idle for idle, _ in TIMEOUTS.values())
    deleted = {
        "audit_event": await _prune(
            db, AuditEvent, col(AuditEvent.created_at) < now - settings.audit_period
        ),
        "job_run": await _prune(
            db,
            JobRun,
            col(JobRun.status).in_(_FINISHED),
            col(JobRun.finished_at) < now - settings.job_run_period,
        ),
        "auth_session": await _prune(
            db,
            AuthSession,
            or_(
                col(AuthSession.expires_at) <= now,
                col(AuthSession.last_seen_at) <= now - longest_idle,
            ),
        ),
    }
    tally = _Tally()
    await _complete_deletions(db, sink, tally)
    if (period := settings.source_period) is not None:
        for expired in _expired_versions(period, now):
            await _prune_versions(db, sink, tally, *expired)
    deleted |= {
        "source_version": tally.versions,
        "source": tally.sources,
        "sink_folder": await _prune_orphans(db, sink),
    }
    async with db.session() as session:
        audit.record(session, actor=None, action="retention.pruned", details=deleted)
    return deleted


async def run(
    db: Database, sink: Sink, settings: RetentionSettings, every: timedelta | None
) -> None:
    """Prune once, or every `every` until SIGINT or SIGTERM (a failed round is retried)."""
    if every is None:
        await prune(db, sink, settings, utcnow())
        return

    async def rounds() -> None:
        while True:
            try:
                await prune(db, sink, settings, utcnow())
            except Exception:  # noqa: BLE001  # e.g. the database is down: next round
                raise_if_cancelled()
                _log.exception("retention.failed")
            await asyncio.sleep(every.total_seconds())

    task = asyncio.create_task(rounds())
    await stop_requested()
    task.cancel()
    # Bounded: a round that does not end is left behind, so that the process can exit.
    if not (await asyncio.wait({task}, timeout=_STOP_SECONDS))[0]:
        _log.warning("retention.stop_timed_out")
