"""SDK-local counters and lifecycle observations; no prompts leave this boundary."""

import asyncio
from collections.abc import Awaitable, Mapping
from time import monotonic_ns
from typing import Any, Protocol

from agents import Agent, AgentHooks, ModelResponse, RunContextWrapper
from agents.run_config import CallModelData, ModelInputData

from agents_factory.modules.runtime.contracts import AgentTurnInput, RuntimeUsage
from agents_factory.modules.runtime.errors import (
    AgentRuntimeError,
    RuntimeToolLimitExceeded,
)


class InputTokenCounter(Protocol):
    async def count(self, data: CallModelData[Any], *, model: str) -> int: ...


async def finish_observation(operation: Awaitable[None]) -> None:
    # Once a provider has returned, a cancelled conversation must not discard its
    # accounting. Only this small database operation is shielded, never the model.
    task = asyncio.ensure_future(operation)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def count(value: object, key: str) -> int | None:
    found = value.get(key) if isinstance(value, Mapping) else getattr(value, key, None)
    return found if type(found) is int and 0 <= found <= 10**15 else None


def response_usage(raw: Mapping[str, object] | None) -> RuntimeUsage:
    # SDK-normalized Usage defaults missing fields to zero. Only the preserved
    # provider payload can distinguish missing values from explicit zeroes.
    raw = raw or {}
    input_tokens = count(raw, "input_tokens")
    output_tokens = count(raw, "output_tokens")
    cached = count(raw.get("input_tokens_details"), "cached_tokens")
    reasoning = count(raw.get("output_tokens_details"), "reasoning_tokens")
    if input_tokens is not None and cached is not None and cached > input_tokens:
        cached = None
    if (
        output_tokens is not None
        and reasoning is not None
        and reasoning > output_tokens
    ):
        reasoning = None
    return RuntimeUsage(
        requests=1,
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
        total_tokens=(
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        ),
    )


class RuntimeMeter(AgentHooks[Any]):
    def __init__(
        self,
        turn: AgentTurnInput,
        *,
        input_token_counter: InputTokenCounter | None = None,
    ) -> None:
        self.turn = turn
        self.input_token_counter = input_token_counter
        self.max_tools = min(
            turn.agent_spec.limits.max_tool_calls,
            turn.execution.max_tool_calls if turn.execution else 32,
        )
        self.max_tokens = turn.execution.max_model_tokens if turn.execution else None
        self.tools_started = 0
        self.responses = 0
        self.total_tokens: int | None = 0
        self.started_at: int | None = None
        self.observed: list[RuntimeUsage] = []

    async def filter_input(self, data: CallModelData[Any]) -> ModelInputData:
        if self.max_tokens is not None:
            if self.total_tokens is None:
                raise AgentRuntimeError("runtime_usage_unknown", retryable=False)
            remaining = self.max_tokens - self.total_tokens
            if remaining <= 0:
                raise AgentRuntimeError("runtime_model_token_limit", retryable=False)
            if self.input_token_counter is None:
                raise AgentRuntimeError(
                    "runtime_input_token_counter_missing", retryable=False
                )
            if self.turn.admission:
                await self.turn.admission.before_input_token_count()
            input_tokens = await self.input_token_counter.count(
                data, model=self.turn.agent_spec.model.model
            )
            if type(input_tokens) is not int or input_tokens < 0:
                raise AgentRuntimeError(
                    "runtime_input_token_count_invalid", retryable=False
                )
            remaining -= input_tokens
            # At least one output token must fit. The provider receives the
            # smaller of the per-response and whole-run allowances.
            if remaining <= 0:
                raise AgentRuntimeError("runtime_model_token_limit", retryable=False)
            data.agent.model_settings.max_tokens = min(
                self.turn.agent_spec.limits.max_output_tokens, remaining
            )
        return data.model_data

    def start_tool(self) -> int:
        if self.tools_started >= self.max_tools:
            raise RuntimeToolLimitExceeded
        # Reserve synchronously before the first await; even parallel SDK tool
        # dispatch and failed validation/handlers consume a technical attempt.
        self.tools_started += 1
        return monotonic_ns()

    async def finish_tool(self, name: str, started_at: int) -> None:
        if self.turn.observer:
            await finish_observation(
                self.turn.observer.tool_attempt(name, self.elapsed(started_at))
            )

    async def on_llm_start(
        self,
        context: RunContextWrapper[Any],
        agent: Agent[Any],
        system_prompt: str | None,
        input_items: list[Any],
    ) -> None:
        if self.turn.admission:
            await self.turn.admission.before_model()
        self.started_at = monotonic_ns()

    async def on_llm_end(
        self,
        context: RunContextWrapper[Any],
        agent: Agent[Any],
        response: ModelResponse,
    ) -> None:
        usage = response_usage(response.raw_usage)
        started_at, self.started_at = self.started_at, None
        self.responses += 1
        self.observed.append(usage)
        self.total_tokens = (
            self.total_tokens + usage.total_tokens
            if self.total_tokens is not None and usage.total_tokens is not None
            else None
        )
        if self.turn.observer:
            await finish_observation(
                self.turn.observer.model_response(usage, self.elapsed(started_at))
            )
        # Stop before executing a tool or issuing another request. Input tokens
        # already consumed by this response cannot be reclaimed by a post-call hook.
        if self.max_tokens is not None and self.total_tokens is not None:
            if self.total_tokens > self.max_tokens:
                raise AgentRuntimeError("runtime_model_token_limit", retryable=False)
        if self.max_tokens is not None and self.total_tokens is None:
            raise AgentRuntimeError("runtime_usage_unknown", retryable=False)

    async def unfinished_request(self) -> None:
        started_at, self.started_at = self.started_at, None
        if started_at is not None and self.turn.observer:
            await finish_observation(
                self.turn.observer.model_response(
                    response_usage(None), self.elapsed(started_at)
                )
            )

    def aggregate(self) -> RuntimeUsage:
        def summed(field: str) -> int | None:
            values = [getattr(value, field) for value in self.observed]
            return None if any(v is None for v in values) else sum(values)

        return RuntimeUsage(
            requests=summed("requests"),
            input_tokens=summed("input_tokens"),
            cached_input_tokens=summed("cached_input_tokens"),
            output_tokens=summed("output_tokens"),
            reasoning_tokens=summed("reasoning_tokens"),
            total_tokens=summed("total_tokens"),
        )

    @staticmethod
    def elapsed(started_at: int | None) -> int:
        return 0 if started_at is None else (monotonic_ns() - started_at) // 1_000_000
