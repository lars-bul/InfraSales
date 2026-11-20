"""Least privilege on PostgreSQL: what the app and the retention job may do, table by table.

The schema owner runs `infrasales migrate`, which applies this after every upgrade, so new tables
are covered at once (a test fails when a table is missing here). The app cannot change or
delete audit events, which makes the audit trail append-only for everything but retention.
"""

from collections.abc import Callable, Mapping
from typing import Literal

from sqlalchemy import create_engine, pool

from infrasales.core.schema import sync_url

type Grantee = Literal["app", "retention"]

POLICY: Mapping[str, Mapping[Grantee, str]] = {
    "alembic_version": {"app": "SELECT"},
    "auth_session": {"app": "SELECT, INSERT, UPDATE, DELETE", "retention": "SELECT, DELETE"},
    "audit_event": {"app": "SELECT, INSERT", "retention": "SELECT, INSERT, DELETE"},
    "config_entry": {"app": "SELECT, INSERT, UPDATE"},
    "job_run": {"app": "SELECT, INSERT, UPDATE", "retention": "SELECT, DELETE"},
    "job_step": {"app": "SELECT, INSERT"},
    "job_trigger": {"app": "SELECT, INSERT"},
    # Admins delete a Feed that has collected no Sources (the foreign keys refuse it otherwise).
    "feed": {"app": "SELECT, INSERT, UPDATE, DELETE"},
    # The scrape sweeps a crash's `writing` versions (and Sources left without any); retention
    # deletes expired versions and empty Sources, files first (ADR 03 §3, §8).
    "source": {"app": "SELECT, INSERT, UPDATE, DELETE", "retention": "SELECT, UPDATE, DELETE"},
    "source_version": {
        "app": "SELECT, INSERT, UPDATE, DELETE",
        "retention": "SELECT, UPDATE, DELETE",
    },
    # The project file (ADR 06 §2): public facts. Claims and events are added, never deleted;
    # a claim's review changes its state. Projects and actors are merged, never deleted.
    "municipality": {"app": "SELECT, INSERT, UPDATE"},
    "actor": {"app": "SELECT, INSERT, UPDATE"},
    "project": {"app": "SELECT, INSERT, UPDATE"},
    "claim": {"app": "SELECT, INSERT, UPDATE"},
    "project_actor": {"app": "SELECT, INSERT, DELETE"},
    "project_event": {"app": "SELECT, INSERT"},
    # What the forecast reads (ADR 06 §4, Modell A): imported again with the same ref, updated.
    "signal": {"app": "SELECT, INSERT, UPDATE"},
    "municipality_metric": {"app": "SELECT, INSERT, UPDATE"},
    "tender": {"app": "SELECT, INSERT, UPDATE"},
    # Models are kept for their backtests; a day's predictions are replaced when made again.
    "forecast_model": {"app": "SELECT, INSERT, UPDATE"},
    "prediction": {"app": "SELECT, INSERT, DELETE"},
    "post_code": {"app": "SELECT, INSERT, UPDATE, DELETE"},  # replaced by each OpenPLZ import
    "tender_award": {"app": "SELECT, INSERT, UPDATE"},
    # Tenants (ADR 06 §3). Members and subscriptions change; private rows are the tenant's to
    # change and delete, under row-level security.
    "tenant": {"app": "SELECT, INSERT, UPDATE"},
    "membership": {"app": "SELECT, INSERT, UPDATE, DELETE"},
    "subscription": {"app": "SELECT, INSERT, UPDATE, DELETE"},
    "company_profile": {"app": "SELECT, INSERT, UPDATE, DELETE"},
    "company_site": {"app": "SELECT, INSERT, UPDATE, DELETE"},
    "bid": {"app": "SELECT, INSERT, UPDATE, DELETE"},
    "pursuit": {"app": "SELECT, INSERT, UPDATE, DELETE"},
}


def statements(roles: Mapping[Grantee, str], quote: Callable[[str], str]) -> list[str]:
    """Revoke everything from each role, then grant what the policy allows it."""
    result: list[str] = []
    for grantee, role in roles.items():
        name = quote(role)
        result += [
            f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {name}",
            f"GRANT USAGE ON SCHEMA public TO {name}",
        ]
        result += [
            f"GRANT {privileges[grantee]} ON {quote(table)} TO {name}"
            for table, privileges in POLICY.items()
            if grantee in privileges
        ]
    return result


def grant(url: str, roles: Mapping[Grantee, str]) -> None:
    """Apply the policy to `roles` in one transaction, as the schema owner at `url`."""
    engine = create_engine(sync_url(url), poolclass=pool.NullPool)
    try:
        with engine.begin() as connection:
            quote = connection.dialect.identifier_preparer.quote
            for statement in statements(roles, quote):
                connection.exec_driver_sql(statement)
    finally:
        engine.dispose()
