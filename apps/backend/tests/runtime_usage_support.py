import asyncio
from dataclasses import replace

from agents import Model, ModelResponse, Runner, Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from agents_factory.modules.runtime.contracts import RuntimeTool


RAW_USAGE = {
    "input_tokens": 7,
    "input_tokens_details": {"cached_tokens": 2},
    "output_tokens": 3,
    "output_tokens_details": {"reasoning_tokens": 1},
    "total_tokens": 10,
}


class LocalModel(Model):
    """Real SDK loop, synthetic transport; it never initializes an API client."""

    def __init__(self, *, raw_usage=RAW_USAGE, tool_calls=0, wait=False):
        self.raw_usage = raw_usage
        self.tool_calls = tool_calls
        self.wait = wait
        self.started = asyncio.Event()
        self.calls = []

    async def get_response(self, **kwargs):
        self.calls.append(kwargs)
        self.started.set()
        if self.wait:
            await asyncio.Event().wait()
        number = len(self.calls)
        output = (
            [
                ResponseFunctionToolCall(
                    id=f"fc_{number}_{index}",
                    call_id=f"call_{number}_{index}",
                    type="function_call",
                    name="orders__lookup",
                    arguments="{}",
                )
                for index in range(self.tool_calls)
            ]
            if self.tool_calls
            else [
                ResponseOutputMessage(
                    id=f"msg_{number}",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[
                        ResponseOutputText(
                            type="output_text",
                            text="Respuesta simulada.",
                            annotations=[],
                        )
                    ],
                )
            ]
        )
        return ModelResponse(
            output=output,
            usage=Usage(requests=1, input_tokens=7, output_tokens=3, total_tokens=10),
            response_id=f"resp_{number}",
            raw_usage=self.raw_usage,
        )

    async def stream_response(self, **kwargs):
        raise AssertionError("streaming is outside this runtime")
        yield


class LocalRunner:
    def __init__(self, model):
        self.model = model

    async def run(self, agent, input_items, *, max_turns, run_config):
        agent.model = self.model
        run_config.tracing_disabled = True
        assert agent.model_settings.retry.max_retries == 0
        assert agent.model_settings.preserve_raw_usage is True
        return await Runner.run(
            agent, input_items, max_turns=max_turns, run_config=run_config
        )


def with_order_tool(turn, handler):
    return replace(
        turn,
        agent_spec=replace(
            turn.agent_spec,
            active_capabilities=frozenset({"orders"}),
            permitted_tools=frozenset({"orders.lookup"}),
        ),
        tools=(
            RuntimeTool(
                name="orders.lookup",
                capability="orders",
                description="Local test operation",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                    "required": [],
                },
                handler=handler,
            ),
        ),
    )
