"""Cross-worker slots without cross-tenant reads or long SQL transactions."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from typing import AsyncIterator, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)


def _key(value: str) -> int:
    return int.from_bytes(sha256(value.encode()).digest()[:8], "big", signed=True)


class AudioCapacityLost(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioCapacityLease:
    connection: AsyncConnection = field(repr=False)
    backend_pid: int

    async def check(self) -> None:
        try:
            pid = await self.connection.scalar(text("SELECT pg_backend_pid()"))
            if pid != self.backend_pid:
                raise AudioCapacityLost("audio_capacity_session_changed")
        except Exception:
            raise AudioCapacityLost("audio_capacity_connection_lost") from None


class AudioCapacityGuard:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        bound = session_factory.kw.get("bind")
        self.engine = cast(
            AsyncEngine, bound.engine if isinstance(bound, AsyncConnection) else bound
        )

    @asynccontextmanager
    async def hold(self, tenant_id: UUID) -> AsyncIterator[AudioCapacityLease | None]:
        connection = await self.engine.connect()
        acquired: list[int] = []
        try:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            tenant_key = _key(f"voice:tenant:{tenant_id}")
            if await connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": tenant_key}
            ):
                acquired.append(tenant_key)
                for slot in range(2):
                    key = _key(f"voice:global:{slot}")
                    if await connection.scalar(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                    ):
                        acquired.append(key)
                        break
            pid = await connection.scalar(text("SELECT pg_backend_pid()"))
            yield AudioCapacityLease(connection, pid) if len(acquired) == 2 else None
        finally:
            try:
                for key in reversed(acquired):
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                    )
            except BaseException:
                await connection.invalidate()
                raise
            finally:
                await connection.close()
