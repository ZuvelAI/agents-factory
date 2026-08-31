import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.backend.tests.contract.runtime.test_openai_adapter import _turn
from apps.backend.tests.runtime_usage_support import (
    LocalModel,
    LocalRunner,
    with_order_tool,
)
from agents_factory.modules.runtime.contracts import RuntimeExecutionPolicy
from agents_factory.modules.runtime.errors import AgentRuntimeError
from agents_factory.modules.runtime.metering import response_usage
from agents_factory.modules.runtime.openai_adapter import OpenAIAgentsRuntime


class Observer:
    def __init__(self):
        self.models = []
        self.tools = []

    async def model_response(self, usage, latency_ms):
        self.models.append(usage)
        assert latency_ms >= 0

    async def tool_attempt(self, name, latency_ms):
        self.tools.append(name)
        assert latency_ms >= 0


async def test_sdk_parallel_tool_burst_and_failed_attempts_are_bounded():
    observer, calls = Observer(), []

    async def handler(context, arguments):
        calls.append(context)
        return {"found": True}

    model = LocalModel(tool_calls=5)
    turn = replace(
        with_order_tool(_turn(), handler),
        execution=RuntimeExecutionPolicy(max_tool_calls=1, max_model_tokens=100),
        observer=observer,
    )
    runtime = OpenAIAgentsRuntime(runner=LocalRunner(model), require_api_key=False)
    with pytest.raises(AgentRuntimeError) as failed:
        await runtime.run(turn)
    assert failed.value.code == "runtime_tool_limit_exceeded"
    assert failed.value.retryable is False
    assert len(calls) == len(observer.tools) == 1
    assert len(model.calls) == len(observer.models) == 1

    # A failing handler still reserves its attempt before another invocation.
    async def broken(context, arguments):
        calls.append(context)
        raise ValueError("synthetic failure")

    class RetryToolRunner:
        async def run(self, agent, input_items, **kwargs):
            tool = agent.tools[0]
            with pytest.raises(ValueError):
                await tool.on_invoke_tool(SimpleNamespace(), "{}")
            await tool.on_invoke_tool(SimpleNamespace(), "{}")

    with pytest.raises(AgentRuntimeError, match="runtime_tool_limit_exceeded"):
        await OpenAIAgentsRuntime(runner=RetryToolRunner(), require_api_key=False).run(
            with_order_tool(turn, broken)
        )
    assert len(calls) == len(observer.tools) == 2


async def test_token_stop_uses_raw_usage_and_prevents_followup_tools():
    assert response_usage({"input_tokens": True}).input_tokens is None
    assert response_usage({}).cached_input_tokens is None
    assert (
        response_usage(
            {"input_tokens_details": {"cached_tokens": 0}}
        ).cached_input_tokens
        == 0
    )
    for raw, code in [
        (None, "runtime_usage_unknown"),
        ({"input_tokens": 100, "output_tokens": 1}, "runtime_model_token_limit"),
    ]:
        observer, model = Observer(), LocalModel(raw_usage=raw, tool_calls=1)

        async def forbidden(context, arguments):
            raise AssertionError("a blocked response cannot execute business tools")

        turn = replace(
            with_order_tool(_turn(), forbidden),
            execution=RuntimeExecutionPolicy(max_tool_calls=1, max_model_tokens=100),
            observer=observer,
        )
        with pytest.raises(AgentRuntimeError, match=code) as failure:
            await OpenAIAgentsRuntime(
                runner=LocalRunner(model), require_api_key=False
            ).run(turn)
        assert failure.value.retryable is False
        assert len(model.calls) == len(observer.models) == 1
        assert model.calls[0]["model_settings"].max_tokens == 100
        assert observer.tools == []
        assert observer.models[0].cached_input_tokens is None


async def test_cancelled_provider_attempt_is_recorded_as_unknown_not_free():
    observer, model = Observer(), LocalModel(wait=True)
    runtime = OpenAIAgentsRuntime(runner=LocalRunner(model), require_api_key=False)
    task = asyncio.create_task(runtime.run(replace(_turn(), observer=observer)))
    await asyncio.wait_for(model.started.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(observer.models) == 1
    assert observer.models[0].requests == 1
    assert observer.models[0].input_tokens is None
    assert observer.models[0].output_tokens is None
