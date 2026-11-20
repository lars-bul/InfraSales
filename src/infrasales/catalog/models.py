"""The catalog: Sources (one per address) and their Source Versions (one per text), ADR 03 §3.

With the folder format in the sink, these two tables are the whole contract with the next
stage: it reads `committed` versions only, and `source.latest_version_id` names the newest.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint, Uuid
from sqlmodel import Field

from infrasales.core.models import BaseTable, UTCDateTime, enum_type
from infrasales.feeds.models import MAX_URL_LENGTH
from infrasales.fetch.fetcher import Validators

MAX_TITLE_LENGTH = 500  # a longer title is cut: the full one stays in `extracted.json`


class VersionState(StrEnum):
    WRITING = "writing"  # files being written: no reader may trust it, a crash leaves it
    COMMITTED = "committed"  # complete and numbered: what the next stage reads
    DELETED = "deleted"  # being deleted: its folder goes first, then its row


class Source(BaseTable, table=True):
    """A document at one address. Created with its first version; the address never changes."""

    url: str = Field(max_length=MAX_URL_LENGTH)  # normalised (`infrasales.catalog.urls`)
    url_hash: str = Field(max_length=64, unique=True)  # sha256 of `url`: the lookup key
    first_feed_id: uuid.UUID = Field(foreign_key="feed.id")  # the Feed that listed it first
    first_seen_at: datetime = Field(sa_type=UTCDateTime)
    last_checked_at: datetime = Field(sa_type=UTCDateTime, index=True)  # retention counts from it
    etag: str | None = Field(default=None, max_length=512)  # of the last fetch, as sent
    last_modified: str | None = Field(default=None, max_length=64)  # of the last fetch, as sent
    # The newest committed version, set only when a version commits. The tables point at each
    # other: this key is added after both exist (`use_alter`).
    latest_version_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            Uuid,
            ForeignKey(
                "source_version.id",
                ondelete="SET NULL",
                use_alter=True,
                name="fk_source_latest_version_id_source_version",
            ),
            index=True,  # deleting a version looks for the Source pointing at it
            nullable=True,
        ),
    )

    @property
    def validators(self) -> Validators:
        """What its next check sends, to be answered `304 Not Modified` if nothing changed."""
        return Validators(self.etag, self.last_modified)


class SourceVersion(BaseTable, table=True):
    """The text of a Source at one time: its folder in the sink is `storage_key`.

    Written as `writing`, numbered at commit: `version_no` orders a Source's versions, there is
    no link to the version before.
    """

    __table_args__ = (
        UniqueConstraint("source_id", "version_no"),
        Index("ix_source_version_state_superseded_at", "state", "superseded_at"),  # sweep, prune
    )

    source_id: uuid.UUID = Field(foreign_key="source.id")
    version_no: int | None = None  # NULL until commit
    # The run that wrote it; job runs are pruned long before versions, which then keep NULL.
    run_id: uuid.UUID | None = Field(
        default=None, foreign_key="job_run.id", ondelete="SET NULL", index=True
    )
    feed_id: uuid.UUID = Field(foreign_key="feed.id")  # the Feed it was filed under
    fetched_at: datetime = Field(sa_type=UTCDateTime)
    http_status: int | None = None  # None: the Feed carried the content (API items)
    media_type: str = Field(max_length=255)
    raw_sha256: str = Field(max_length=64)
    text_sha256: str = Field(max_length=64)  # what changes are detected by
    extractor: str = Field(max_length=64)
    extractor_version: str = Field(max_length=64)
    storage_key: str = Field(max_length=1024)  # its folder: `<run>/<feed slug>/<id>`
    partial: bool = False  # only what the Feed said (a paywall), or too little text
    # What the extractor read, as in `extracted.json`: the catalog lists and searches by it.
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    published_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    state: VersionState = Field(default=VersionState.WRITING, sa_type=enum_type(VersionState))
    superseded_at: datetime | None = Field(default=None, sa_type=UTCDateTime)  # a newer one came
    # Kept at least until then (a claim in the project file cites it).
    retain_until: datetime | None = Field(default=None, sa_type=UTCDateTime)
