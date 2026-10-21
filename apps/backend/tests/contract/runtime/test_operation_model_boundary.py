"""Exercise the real SDK loop without a provider or credentials."""

from dataclasses import replace

import pytest
from agents import Model, ModelResponse, Runner, Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from agents_factory.modules.runtime.contracts import RuntimeTool
from agents_factory.modules.runtime.openai_adapter import (
    AgentRuntimeError,
    OpenAIAgentsRuntime,
)
from apps.backend.tests.contract.runtime.test_openai_adapter import _turn


@pytest.mark.asyncio
async def test_pause_during_tool_prevents_next_real_sdk_model_call():
    permitted = True
    calls = []

    async def eligible():
        return permitted

    async def handler(context, arguments):
        nonlocal permitted
        permitted = False
        return {"status": "done"}

    class LocalModel(Model):
        async def get_response(self, *args, **kwargs):
            calls.append(permitted)
            output = (
                [
                    ResponseFunctionToolCall(
                        type="function_call",
                        name="business__lookup",
                        arguments="{}",
                        call_id="local-call",
                        id="local-tool",
                    )
                ]
                if len(calls) == 1
                else [
                    ResponseOutputMessage(
                        type="message",
                        id="local-message",
                        role="assistant",
                        status="completed",
                        content=[
                            ResponseOutputText(
                                type="output_text", text="Done", annotations=[]
                            )
                        ],
                    )
                ]
            )
            return ModelResponse(
                output=output, usage=Usage(), response_id=f"local-{len(calls)}"
            )

        async def stream_response(self, *args, **kwargs):
            raise AssertionError("streaming not used")
            yield

    class LocalRunner:
        async def run(self, agent, input_items, *, max_turns, run_config):
            agent.model = LocalModel()
            run_config.tracing_disabled = True
            return await Runner.run(
                agent, input_items, max_turns=max_turns, run_config=run_config
            )

    turn = replace(
        _turn(),
        tools=(
            RuntimeTool(
                name="business.lookup",
                capability="business",
                description="Local lookup",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=handler,
            ),
        ),
    )
    guarded = replace(turn, model_eligible=eligible)
    try:
        await OpenAIAgentsRuntime(runner=LocalRunner(), require_api_key=False).run(
            guarded
        )
    except AgentRuntimeError as error:
        assert error.code == "agent_operation_ineligible"
    assert calls == [True]
