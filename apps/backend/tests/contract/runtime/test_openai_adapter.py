from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from agents_factory.modules.runtime.contracts import (
    AgentSpecSnapshot,
    AgentTurnInput,
    ModelConfiguration,
    RuntimeLimits,
    RuntimeTraceMetadata,
    TurnMessage,
)
from agents_factory.modules.runtime.openai_adapter import OpenAIAgentsRuntime


@dataclass
class _CapturedRunner:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run(
        self,
        agent: Any,
        input_items: list[dict[str, object]],
        *,
        max_turns: int,
        run_config: Any,
    ) -> Any:
        self.calls.append(
            {
                "agent": agent,
                "input_items": input_items,
                "max_turns": max_turns,
                "run_config": run_config,
            }
        )
        usage = SimpleNamespace(
            requests=1,
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
            input_tokens_details=SimpleNamespace(cached_tokens=20),
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        )
        return SimpleNamespace(
            final_output="Tu pedido está en preparación.",
            context_wrapper=SimpleNamespace(usage=usage),
            last_response_id="resp_recorded_001",
        )


def _turn() -> AgentTurnInput:
    tenant_id = uuid4()
    conversation_id = uuid4()
    inbound_message_id = uuid4()
    spec = AgentSpecSnapshot(
        id=uuid4(),
        tenant_id=tenant_id,
        version="runtime-v1",
        digest="b" * 64,
        product="customer_service",
        product_version="1.0.0",
        instructions="Answer as the configured customer-service agent.",
        active_capabilities=frozenset(),
        permitted_tools=frozenset(),
        model=ModelConfiguration(),
        limits=RuntimeLimits(
            max_output_tokens=700,
            max_tool_calls=4,
            timeout_seconds=15.0,
        ),
        active=True,
    )
    return AgentTurnInput(
        agent_spec=spec,
        messages=(
            TurnMessage(
                id=inbound_message_id,
                role="user",
                text="¿Dónde está mi pedido?",
            ),
        ),
        tools=(),
        trace=RuntimeTraceMetadata(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
            correlation_id=uuid4(),
            agent_spec_id=spec.id,
            agent_spec_digest=spec.digest,
        ),
    )


@pytest.mark.asyncio
async def test_selected_gpt6_luna_is_used_by_sdk_with_existing_reasoning_limits():
    turn = _turn()
    selected = replace(
        turn,
        agent_spec=replace(
            turn.agent_spec, model=ModelConfiguration(model="gpt-6-luna")
        ),
    )
    runner = _CapturedRunner()
    result = await OpenAIAgentsRuntime(runner=runner, require_api_key=False).run(
        selected
    )
    assert result.output_text == "Tu pedido está en preparación."
    agent = runner.calls[0]["agent"]
    assert agent.model == "gpt-6-luna"
    assert agent.model_settings.reasoning.effort == "low"


@pytest.mark.asyncio
@pytest.mark.parametrize("new_contact", [True, False])
async def test_server_welcome_preserves_answer_and_is_not_sent_to_existing_contacts(
    new_contact,
):
    original = _turn()
    turn = replace(
        original,
        agent_spec=replace(
            original.agent_spec,
            first_contact_greeting="Bienvenido a Zuvel.\n• *Servicios empresariales*",
        ),
        is_first_contact=new_contact,
    )
    runner = _CapturedRunner()
    result = await OpenAIAgentsRuntime(runner=runner, require_api_key=False).run(turn)
    assert result.output_text == (
        "Bienvenido a Zuvel.\n• *Servicios empresariales*\n\nTu pedido está en preparación."
        if new_contact
        else "Tu pedido está en preparación."
    )
    assert result.usage.total_tokens == 150
    assert result.provider_response_id == "resp_recorded_001"
    assert runner.calls[0]["agent"].instructions != original.agent_spec.instructions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Hola",
        "¡Buenos días!",
        "Hola, quisiera conocer la empresa.",
        "¿Qué servicios ofrece la empresa según la información aprobada?",
    ],
)
async def test_general_first_contact_uses_complete_welcome_without_second_introduction(
    message,
):
    original = _turn()
    turn = replace(
        original,
        agent_spec=replace(
            original.agent_spec,
            first_contact_greeting="Bienvenido. Ofrecemos agentes y software.",
        ),
        messages=(replace(original.messages[0], text=message),),
        is_first_contact=True,
    )
    result = await OpenAIAgentsRuntime(
        runner=_CapturedRunner(), require_api_key=False
    ).run(turn)
    assert result.output_text == "Bienvenido. Ofrecemos agentes y software."


@pytest.mark.asyncio
async def test_adapter_maps_the_internal_contract_to_one_bounded_sdk_agent() -> None:
    runner = _CapturedRunner()
    runtime = OpenAIAgentsRuntime(runner=runner, require_api_key=False)

    result = await runtime.run(_turn())

    assert result.output_text == "Tu pedido está en preparación."
    assert result.usage.total_tokens == 150
    assert result.usage.cached_input_tokens == 20
    assert result.usage.reasoning_tokens == 5
    assert result.provider_response_id == "resp_recorded_001"
    assert len(runner.calls) == 1

    call = runner.calls[0]
    agent = call["agent"]
    assert agent.model == "gpt-5.6-luna"
    assert agent.handoffs == []
    assert agent.model_settings.max_tokens == 700
    assert agent.model_settings.reasoning.effort == "low"
    assert agent.model_settings.parallel_tool_calls is False
    assert call["max_turns"] == 5
    assert call["input_items"] == [
        {"role": "user", "content": "¿Dónde está mi pedido?"}
    ]
    run_config = call["run_config"]
    assert run_config.trace_include_sensitive_data is False
    assert set(run_config.trace_metadata) == {
        "tenant_id",
        "conversation_id",
        "inbound_message_id",
        "correlation_id",
        "agent_spec_id",
        "agent_spec_digest",
    }
