"""Add the catalog: Feeds, Sources and their Source Versions (ADR 03).

`source` and `source_version` refer to each other: the latest-version key is added once both
exist, and dropped before them. No Feed is seeded: Feeds are added on the Feeds page.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feed",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column(
            "settings", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
        ),
        sa.Column("fetcher", sa.String(length=32), nullable=False),
        sa.Column("extractor", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed")),
        sa.UniqueConstraint("slug", name=op.f("uq_feed_slug")),
        sa.UniqueConstraint("url", name=op.f("uq_feed_url")),
    )
    op.create_table(
        "source",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("first_feed_id", sa.Uuid(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("etag", sa.String(length=512), nullable=True),
        sa.Column("last_modified", sa.String(length=64), nullable=True),
        sa.Column("latest_version_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["first_feed_id"], ["feed.id"], name=op.f("fk_source_first_feed_id_feed")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source")),
        sa.UniqueConstraint("url_hash", name=op.f("uq_source_url_hash")),
    )
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_source_last_checked_at"), ["last_checked_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_source_latest_version_id"), ["latest_version_id"], unique=False
        )

    op.create_table(
        "source_version",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("feed_id", sa.Uuid(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("extractor", sa.String(length=64), nullable=False),
        sa.Column("extractor_version", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("partial", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["feed_id"], ["feed.id"], name=op.f("fk_source_version_feed_id_feed")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["job_run.id"],
            name=op.f("fk_source_version_run_id_job_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["source.id"], name=op.f("fk_source_version_source_id_source")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_version")),
        sa.UniqueConstraint(
            "source_id", "version_no", name=op.f("uq_source_version_source_id_version_no")
        ),
    )
    with op.batch_alter_table("source_version", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_source_version_run_id"), ["run_id"], unique=False)
        batch_op.create_index(
            "ix_source_version_state_superseded_at", ["state", "superseded_at"], unique=False
        )

    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_source_latest_version_id_source_version",
            "source_version",
            ["latest_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.drop_constraint("fk_source_latest_version_id_source_version", type_="foreignkey")

    with op.batch_alter_table("source_version", schema=None) as batch_op:
        batch_op.drop_index("ix_source_version_state_superseded_at")
        batch_op.drop_index(batch_op.f("ix_source_version_run_id"))

    op.drop_table("source_version")
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_latest_version_id"))
        batch_op.drop_index(batch_op.f("ix_source_last_checked_at"))

    op.drop_table("source")
    op.drop_table("feed")
