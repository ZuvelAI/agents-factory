"""Serialize channel authority changes without granting runtime UPDATE rights."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_account_lifecycle(
    session: AsyncSession, tenant_id: UUID, account_id: UUID
) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"account-lifecycle:{tenant_id}:{account_id}"},
    )
