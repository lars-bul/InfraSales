"""Binding a transaction to a tenant: the second guard of the private zone (ADR 06 §3).

Code filters every private query by `tenant_id`. On PostgreSQL the transaction is also bound to
the tenant (`app.tenant_id`, local to the transaction), and row-level security returns only that
tenant's rows: a query that forgot the filter still sees nothing of another tenant. SQLite has no
row-level security; there the code's filter is the only guard (development and tests).
"""

import uuid

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

SETTING = "app.tenant_id"


async def bind(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Bind the session's transaction to `tenant_id` (PostgreSQL; a no-op elsewhere)."""
    if session.get_bind().dialect.name != "postgresql":
        return
    statement = text("SELECT set_config(:setting, :tenant, true)")
    connection = await session.connection()
    await connection.execute(statement, {"setting": SETTING, "tenant": str(tenant_id)})


def policy_sql(table: str) -> list[str]:
    """The statements that put `table` under row-level security by tenant (PostgreSQL)."""
    condition = f"tenant_id = NULLIF(current_setting('{SETTING}', true), '')::uuid"
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {table}_tenant ON {table} USING ({condition}) WITH CHECK ({condition})",
    ]
