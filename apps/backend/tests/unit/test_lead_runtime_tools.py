"""Prepared tools are pure and bound to a single immutable turn."""

from dataclasses import replace
from uuid import uuid4

import pytest

from agents_factory.modules.leads.runtime_tools import lead_tools_for_turn
from agents_factory.modules.leads.privacy import explicit_capture_refusal
from agents_factory.modules.runtime.contracts import ToolInvocationContext, TurnMessage
from apps.backend.tests.contract.runtime.test_openai_adapter import (
    _turn,
    _CapturedRunner,
)
from agents_factory.modules.runtime.openai_adapter import OpenAIAgentsRuntime


def lead_turn():
    turn = _turn()
    return replace(
        turn,
        agent_spec=replace(
            turn.agent_spec,
            active_capabilities=frozenset({"lead_capture"}),
            permitted_tools=frozenset(
                {"lead_capture.propose", "lead_capture.suppress"}
            ),
        ),
        messages=(
            TurnMessage(
                turn.trace.inbound_message_id, "user", "Quiero un agente de ventas"
            ),
        ),
    )


def arguments(turn, operation="CAPTURE"):
    return {
        "operation": operation,
        "evidence": [
            {
                "message_id": str(turn.trace.inbound_message_id),
                "quote": turn.messages[-1].text,
            }
        ],
    }


def invocation(turn):
    return ToolInvocationContext(
        turn.trace.tenant_id,
        turn.trace.conversation_id,
        turn.trace.inbound_message_id,
        turn.trace.correlation_id,
    )


async def test_prepared_tools_require_both_permissions_and_do_not_persist():
    turn = lead_turn()
    assert (
        lead_tools_for_turn(
            replace(
                turn, agent_spec=replace(turn.agent_spec, permitted_tools=frozenset())
            ),
            simulation=False,
        )
        == ()
    )
    tool, suppress = lead_tools_for_turn(turn, simulation=False)
    assert (
        tool.name == "lead_capture.propose" and suppress.name == "lead_capture.suppress"
    )
    result = await tool.handler(invocation(turn), arguments(turn))
    assert result == {"status": "PREPARED", "operation": "CAPTURE", "simulated": False}
    with pytest.raises(ValueError):
        await tool.handler(invocation(turn), arguments(turn))
    with pytest.raises(ValueError):
        await suppress.handler(
            replace(invocation(turn), tenant_id=uuid4()), arguments(turn, "SUPPRESS")
        )


@pytest.mark.parametrize("invalid", ["foreign", "assistant", "invented", "secret"])
async def test_tool_rejects_false_evidence_and_credential_data(invalid):
    turn = lead_turn()
    if invalid == "assistant":
        turn = replace(
            turn,
            messages=(
                TurnMessage(uuid4(), "assistant", "Quiero un agente de ventas"),
                *turn.messages,
            ),
        )
    args = arguments(turn)
    if invalid == "foreign":
        args["evidence"][0]["message_id"] = str(uuid4())
    elif invalid == "assistant":
        args["evidence"][0]["message_id"] = str(turn.messages[0].id)
    elif invalid == "invented":
        args["declared_company"] = "Empresa inventada"
    else:
        args["need_summary"] = "sk-proj-" + "X" * 40
    with pytest.raises(ValueError):
        await lead_tools_for_turn(turn, simulation=False)[0].handler(
            invocation(turn), args
        )


async def test_validation_error_does_not_echo_the_rejected_payload():
    turn = lead_turn()
    args = arguments(turn)
    args["declared_company"] = "PRIVATE_COMPANY_NOT_IN_MESSAGE"
    args["need_summary"] = "sk-proj-" + "X" * 40
    args["unrecognized"] = "PRIVATE_COMPANY_NOT_IN_MESSAGE"
    with pytest.raises(ValueError) as error:
        await lead_tools_for_turn(turn, simulation=False)[0].handler(
            invocation(turn), args
        )
    assert "PRIVATE_COMPANY" not in str(error.value)
    assert "sk-proj-" not in str(error.value)


async def test_sdk_sees_server_message_ids_only_for_enabled_capability():
    turn = lead_turn()
    runner = _CapturedRunner()
    runtime = OpenAIAgentsRuntime(runner=runner, require_api_key=False)
    turn = replace(turn, tools=lead_tools_for_turn(turn, simulation=True))
    await runtime.run(turn)
    request = runner.calls[0]
    assert str(turn.trace.inbound_message_id) in str(request["input_items"])
    for tool in request["agent"].tools:
        assert tool.params_json_schema["additionalProperties"] is False
        assert set(tool.params_json_schema["required"]) == set(
            tool.params_json_schema["properties"]
        )
    assert "PREPARED" in request["agent"].instructions


@pytest.mark.parametrize(
    "body",
    [
        "No guardes mis datos como prospecto",
        "Por favor, no registres mis datos.",
        "No quiero que guardes mis datos",
        "Do not save my data as a lead",
        "Don't store my data",
    ],
)
def test_direct_refusal_is_recognized(body):
    assert explicit_capture_refusal(body)


@pytest.mark.parametrize(
    "body",
    [
        "Hola",
        "Quiero un agente",
        'Un ejemplo es: "No guardes mis datos"',
        'El asistente dijo "no registres mis datos"',
        '"No guardes mis datos"',
        "¿Qué pasa si un cliente dice no guardes mis datos?",
    ],
)
def test_quoted_or_ambiguous_refusal_is_not_customer_denial(body):
    assert not explicit_capture_refusal(body)
