"""Ephemeral tenant coordination in Redis; business evidence stays in Postgres."""

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from agents_factory.common.deferral import JobDeferred
from agents_factory.modules.runtime.errors import AgentRuntimeError
from agents_factory.modules.usage.models import TechnicalLimits


_SCRIPT = """
local time = redis.call('TIME')
local now = tonumber(time[1])*1000 + math.floor(tonumber(time[2])/1000)
local op, run = ARGV[1], ARGV[2]
if op == 'release' then
  redis.call('ZREM', KEYS[1], run)
  return {1, 0, 0}
end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
local active = redis.call('ZCARD', KEYS[1])
if op == 'acquire' then
  if redis.call('ZSCORE', KEYS[1], run) then return {-1, 0, active} end
  if active >= tonumber(ARGV[4]) then
    local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return {0, math.max(1, tonumber(first[2])-now), active}
  end
  redis.call('ZADD', KEYS[1], now+tonumber(ARGV[3]), run)
  redis.call('PEXPIRE', KEYS[1], 310000)
  return {1, 0, active+1}
end
if not redis.call('ZSCORE', KEYS[1], run) then return {-1, 0, active} end
if op == 'request' then
  redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now-60000)
  if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[5]) then
    local first = redis.call('ZRANGE', KEYS[2], 0, 0, 'WITHSCORES')
    return {0, math.max(1, tonumber(first[2])+60000-now), active}
  end
  redis.call('ZADD', KEYS[2], now, ARGV[6])
  redis.call('PEXPIRE', KEYS[2], 61000)
end
return {1, 0, active}
"""


class UsageCapacity:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def keys(tenant_id: UUID) -> tuple[str, str]:
        prefix = f"usage:{{{tenant_id}}}"
        return f"{prefix}:runs", f"{prefix}:requests"

    async def command(
        self,
        operation: str,
        tenant_id: UUID,
        run_id: UUID,
        *,
        duration_ms: int = 0,
        concurrency: int = 0,
        rate: int = 0,
    ) -> tuple[int, int, int]:
        async with asyncio.timeout(3):
            result = await cast(
                Awaitable[object],
                self.redis.eval(
                    _SCRIPT,
                    2,
                    *self.keys(tenant_id),
                    operation,
                    str(run_id),
                    str(duration_ms),
                    str(concurrency),
                    str(rate),
                    uuid4().hex,
                ),
            )
        if (
            not isinstance(result, list)
            or len(result) != 3
            or any(type(v) is not int for v in result)
        ):
            raise AgentRuntimeError("runtime_capacity_invalid", retryable=False)
        return int(result[0]), int(result[1]), int(result[2])

    async def acquire(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        limits: TechnicalLimits,
        timeout_seconds: float,
    ) -> "CapacityLease":
        if not 0 < timeout_seconds <= 300:
            raise ValueError("invalid capacity lease duration")
        try:
            state, delay, active = await self.command(
                "acquire",
                tenant_id,
                run_id,
                duration_ms=round((timeout_seconds + 5) * 1000),
                concurrency=limits.max_concurrent_runs,
            )
        except (RedisError, TimeoutError):
            raise JobDeferred(5) from None
        if state == 0:
            raise JobDeferred(min(30, max(1, delay / 1000)))
        if state != 1:
            raise AgentRuntimeError("runtime_capacity_lost", retryable=False)
        return CapacityLease(
            self, tenant_id, run_id, limits.max_requests_per_minute, active
        )


@dataclass
class CapacityLease:
    capacity: UsageCapacity
    tenant_id: UUID
    run_id: UUID
    rate: int
    active_at_admission: int
    requests_started: int = 0

    async def before_model(self) -> None:
        await self._check("request")
        self.requests_started += 1

    async def before_tool(self) -> None:
        await self._check("check")

    async def _check(self, operation: str) -> None:
        try:
            state, delay, _ = await self.capacity.command(
                operation, self.tenant_id, self.run_id, rate=self.rate
            )
        except (RedisError, TimeoutError):
            if self.requests_started == 0:
                raise JobDeferred(5) from None
            raise AgentRuntimeError(
                "runtime_capacity_unavailable", retryable=False
            ) from None
        if state == 0:
            if self.requests_started == 0:
                raise JobDeferred(max(1, delay / 1000))
            # Never replay a partial agent run/tools as a free capacity retry.
            raise AgentRuntimeError("runtime_rate_limit", retryable=False)
        if state != 1:
            raise AgentRuntimeError("runtime_capacity_lost", retryable=False)

    async def release(self) -> None:
        try:
            await self.capacity.command("release", self.tenant_id, self.run_id)
        except (RedisError, TimeoutError):
            # Keep the original outcome; the bounded lease expires without renewal.
            pass
