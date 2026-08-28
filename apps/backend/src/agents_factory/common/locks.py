from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from time import monotonic
from typing import cast
from uuid import UUID, uuid4

from redis.asyncio import Redis


_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class ConversationLockUnavailable(RuntimeError):
    pass


class ConversationLockLost(RuntimeError):
    pass


class ConversationLockManager:
    def __init__(
        self,
        redis: Redis,
        *,
        lease_seconds: float = 30.0,
        acquire_timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        if not 0.05 <= lease_seconds <= 300:
            raise ValueError("conversation lease must be between 0.05 and 300 seconds")
        if acquire_timeout_seconds <= 0:
            raise ValueError("conversation lock timeout must be positive")
        if not 0 < poll_interval_seconds < acquire_timeout_seconds:
            raise ValueError("conversation lock polling interval is invalid")
        self._redis = redis
        self._lease_seconds = lease_seconds
        self._lease_ms = max(1, round(lease_seconds * 1000))
        self._acquire_timeout_seconds = acquire_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds

    @staticmethod
    def key_for(tenant_id: UUID, conversation_id: UUID) -> str:
        return f"{tenant_id}:{conversation_id}"

    @asynccontextmanager
    async def hold(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
    ) -> AsyncIterator[None]:
        key = self.key_for(tenant_id, conversation_id)
        lease_value = uuid4().hex
        deadline = monotonic() + self._acquire_timeout_seconds
        while True:
            acquired = await self._redis.set(
                key, lease_value, nx=True, px=self._lease_ms
            )
            if acquired:
                break
            if monotonic() >= deadline:
                raise ConversationLockUnavailable(key)
            await asyncio.sleep(self._poll_interval_seconds)

        renewal = asyncio.create_task(self._renew(key=key, lease_value=lease_value))
        renewal_error: BaseException | None = None
        try:
            yield
        finally:
            renewal.cancel()
            try:
                await renewal
            except asyncio.CancelledError:
                pass
            except BaseException as error:
                renewal_error = error
            await cast(
                Awaitable[object],
                self._redis.eval(_RELEASE_SCRIPT, 1, key, lease_value),
            )
            if renewal_error is not None:
                raise renewal_error

    async def _renew(self, *, key: str, lease_value: str) -> None:
        interval = self._lease_seconds / 3
        while True:
            await asyncio.sleep(interval)
            renewed = await cast(
                Awaitable[object],
                self._redis.eval(
                    _RENEW_SCRIPT,
                    1,
                    key,
                    lease_value,
                    str(self._lease_ms),
                ),
            )
            if renewed != 1:
                raise ConversationLockLost(key)
