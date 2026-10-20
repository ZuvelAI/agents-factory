from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

from agents_factory.common.queue import DurableJobRunner, JobDeferral, JobEnvelope


async def test_audio_preflight_runs_before_lock_and_attempt():
    events = []

    @asynccontextmanager
    async def admission(envelope):
        events.append("preflight")
        yield JobDeferral(5)
        events.append("released")

    runner = DurableJobRunner(
        session_factory=AsyncMock(), preflight=admission, conversation_locks=AsyncMock()
    )
    handler = AsyncMock()
    result = await runner.run(
        envelope=JobEnvelope(uuid4(), uuid4(), "agent.turn", uuid4()), handler=handler
    )
    assert result.status == "deferred"
    assert result.retry_after_seconds == 5
    assert result.attempt_number is None
    assert events == ["preflight", "released"]
    handler.assert_not_called()
    runner._conversation_locks.hold.assert_not_called()
    runner._session_factory.begin.assert_not_called()
