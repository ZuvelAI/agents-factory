from collections.abc import Awaitable
from typing import Protocol, cast

from redis.asyncio import Redis


class ApprovalRateLimiter(Protocol):
    async def allow(self, key: str, *, limit: int, seconds: int) -> bool: ...


class RedisApprovalRateLimiter:
    """Shared atomic window; keys contain keyed digests, never IP/email/bearers."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def allow(self, key: str, *, limit: int, seconds: int) -> bool:
        # One script prevents a crash between INCR and EXPIRE leaking a counter.
        result = await cast(
            Awaitable[int],
            self.redis.eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
                1,
                "approvals:rate:" + key,
                str(seconds),
            ),
        )
        return int(result) <= limit
