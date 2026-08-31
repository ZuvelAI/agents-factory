from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.backend.tests.contract.runtime.test_openai_adapter import _turn
from apps.backend.tests.runtime_usage_support import (
    LocalInputTokenCounter,
    LocalModel,
    LocalRunner,
    with_order_tool,
)
from agents_factory.modules.runtime.contracts import RuntimeExecutionPolicy
from agents_factory.modules.runtime.errors import AgentRuntimeError
from agents_factory.modules.runtime.openai_adapter import (
    OpenAIAgentsRuntime,
    OpenAIInputTokenCounter,
)


class CapturedInputTokens:
    def __init__(self, *counts):
        self.counts = list(counts)
        self.calls = []

    async def count(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(input_tokens=self.counts[len(self.calls) - 1])


class CapturedClient:
    def __init__(self, *counts):
        self.input_tokens = CapturedInputTokens(*counts)
        self.responses = SimpleNamespace(input_tokens=self.input_tokens)


class ToolThenAnswerModel(LocalModel):
    def __init__(self):
        super().__init__()
        self.max_tokens = []

    async def get_response(self, **kwargs):
        self.max_tokens.append(kwargs["model_settings"].max_tokens)
        self.tool_calls = 1 if not self.calls else 0
        return await super().get_response(**kwargs)


class Admission:
    def __init__(self):
        self.events = []

    async def before_input_token_count(self):
        self.events.append("input_count")

    async def before_model(self):
        self.events.append("model")

    async def before_tool(self):
        self.events.append("tool")


async def test_exact_preflight_recounts_tools_and_clamps_each_model_response():
    client, admission = CapturedClient(20, 60), Admission()
    model = ToolThenAnswerModel()
    tool_invocations = []

    async def lookup(context, arguments):
        tool_invocations.append(context)
        return {"found": True}

    turn = replace(
        with_order_tool(_turn(), lookup),
        execution=RuntimeExecutionPolicy(max_tool_calls=1, max_model_tokens=100),
        admission=admission,
    )
    result = await OpenAIAgentsRuntime(
        runner=LocalRunner(model),
        require_api_key=False,
        input_token_counter=OpenAIInputTokenCounter(client),  # type: ignore[arg-type]
    ).run(turn)

    assert result.output_text == "Respuesta simulada."
    assert len(model.calls) == len(client.input_tokens.calls) == 2
    assert model.max_tokens == [80, 30]
    assert admission.events == [
        "input_count",
        "model",
        "tool",
        "input_count",
        "model",
    ]
    first, second = client.input_tokens.calls
    assert first["model"] == "gpt-5.6-luna"
    assert first["instructions"] == turn.agent_spec.instructions
    assert first["parallel_tool_calls"] is False
    assert first["tools"] == [
        {
            "name": "orders__lookup",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
                "required": [],
            },
            "strict": True,
            "type": "function",
            "description": "Business operation `orders.lookup`. Local test operation",
        }
    ]
    assert any(item.get("type") == "function_call_output" for item in second["input"])
    assert len(tool_invocations) == 1


@pytest.mark.parametrize(
    ("counter", "runner_input_tokens", "expected"),
    [
        (None, None, "runtime_input_token_counter_missing"),
        (LocalInputTokenCounter(-1), None, "runtime_input_token_count_invalid"),
        (LocalInputTokenCounter(100), None, "runtime_model_token_limit"),
    ],
)
async def test_preflight_fails_closed_before_generation(
    counter, runner_input_tokens, expected
):
    model = LocalModel()
    turn = replace(
        _turn(),
        execution=RuntimeExecutionPolicy(max_tool_calls=0, max_model_tokens=100),
    )
    with pytest.raises(AgentRuntimeError, match=expected) as failure:
        await OpenAIAgentsRuntime(
            runner=LocalRunner(model, input_tokens=runner_input_tokens),
            require_api_key=False,
            input_token_counter=counter,
        ).run(turn)
    assert failure.value.retryable is False
    assert model.calls == []
