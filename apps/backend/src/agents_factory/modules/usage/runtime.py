"""Tenant-scoped accounting around the shared runtime, not a per-client runtime."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic_ns

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.runtime.contracts import (
    AgentRuntime,
    AgentTurnInput,
    AgentTurnResult,
    RuntimeExecutionPolicy,
    RuntimeUsage,
)
from agents_factory.modules.runtime.errors import AgentRuntimeError
from agents_factory.modules.runtime.metering import finish_observation
from agents_factory.modules.usage.models import Measurements, UsageEvent
from agents_factory.modules.usage.recorder import UsageRecorder


class _RunObserver:
    def __init__(
        self, recorder: UsageRecorder, context: TenantContext, turn: AgentTurnInput
    ) -> None:
        self.recorder = recorder
        self.context = context
        self.turn = turn
        self.run_id = new_uuid7()
        self.sequence = 0
        self.model_observations = 0

    async def model_response(self, usage: RuntimeUsage, latency_ms: int) -> None:
        self.model_observations += 1
        await self.record(
            kind="llm",
            provider="openai",
            product=self.turn.agent_spec.model.model,
            measurements=Measurements(
                requests=usage.requests,
                input_tokens=usage.input_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                latency_ms=Decimal(latency_ms),
            ),
        )

    async def tool_attempt(self, name: str, latency_ms: int) -> None:
        await self.record(
            kind="tool",
            provider="agents_factory",
            product=name,
            measurements=Measurements(tool_calls=1, latency_ms=Decimal(latency_ms)),
        )

    async def record(
        self, *, kind: str, provider: str, product: str, measurements: Measurements
    ) -> None:
        self.sequence += 1
        event = UsageEvent.model_validate(
            {
                "source_key": f"runtime:{self.run_id}:{self.sequence}",
                "occurred_at": datetime.now(UTC),
                "kind": kind,
                "provider": provider,
                "product": product,
                "model": product if kind == "llm" else None,
                "currency": "USD",
                "run_id": self.run_id,
                "conversation_id": self.turn.trace.conversation_id,
                "measurements": measurements,
            }
        )
        try:
            await self.recorder.record(context=self.context, event=event)
        except Exception:
            # Re-running a possibly billed call because its accounting failed
            # compounds the gap. Leave a terminal, sanitized operational incident.
            raise AgentRuntimeError("usage_recording_failed", retryable=False) from None


class MeteredAgentRuntime:
    def __init__(
        self, runtime: AgentRuntime, recorder: UsageRecorder, *, attempt_number: int = 1
    ) -> None:
        if attempt_number < 1:
            raise ValueError("invalid durable runtime attempt")
        self.runtime = runtime
        self.recorder = recorder
        self.attempt_number = attempt_number

    async def run(self, turn: AgentTurnInput) -> AgentTurnResult:
        context = TenantContext(
            tenant_id=turn.trace.tenant_id,
            actor_id=turn.trace.correlation_id,
            actor_type="system",
            correlation_id=turn.trace.correlation_id,
        )
        configuration, revision = await self.recorder.configuration(context)
        observer = _RunObserver(self.recorder, context, turn)
        try:
            if self.attempt_number - 1 > configuration.technical.max_retries:
                raise AgentRuntimeError("runtime_retry_limit", retryable=False)
            execution = RuntimeExecutionPolicy(
                max_tool_calls=configuration.technical.max_tool_calls,
                max_model_tokens=configuration.technical.max_model_tokens,
            )
            started_at = monotonic_ns()
            result = await self.runtime.run(
                replace(turn, execution=execution, observer=observer)
            )
            # Internal test/alternative adapters can expose aggregate usage only.
            # The production SDK adapter records every response before side effects.
            if observer.model_observations == 0:
                await finish_observation(
                    observer.model_response(
                        result.usage, (monotonic_ns() - started_at) // 1_000_000
                    )
                )
            return result
        except AgentRuntimeError as error:
            if not error.retryable:
                try:
                    async with self.recorder.transaction(context) as session:
                        await AuditService(session).record(
                            context=context,
                            event_type="usage.runtime_stopped",
                            entity_type="conversation",
                            entity_id=turn.trace.conversation_id,
                            payload={
                                "run_id": str(observer.run_id),
                                "reason_code": error.code,
                                "configuration_revision": revision,
                                "attempt_number": self.attempt_number,
                            },
                        )
                except Exception:
                    # A database outage must not turn a terminal usage failure
                    # into a retryable SQL error and trigger another billed run.
                    raise error from None
            raise
