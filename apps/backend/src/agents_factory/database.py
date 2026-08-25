from collections.abc import AsyncIterator
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Own the async database engine and session factory."""

    def __init__(self, url: SecretStr) -> None:
        self._engine: AsyncEngine = create_async_engine(url.get_secret_value())
        self.session_factory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )

    async def ping(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self._engine.dispose()


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """Set a transaction-local tenant boundary using bound parameters."""

    await session.execute(
        text("SELECT set_config(:setting_name, :tenant_id, true)"),
        {
            "setting_name": "app.tenant_id",
            "tenant_id": str(tenant_id),
        },
    )


async def transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield one session inside a commit-or-rollback transaction boundary."""

    async with session_factory.begin() as session:
        yield session
