"""Preview is pure; old six-case evidence cannot certify prospect tools."""

from uuid import uuid4

from agents_factory.modules.agent_factory.configuration_projection import (
    project_configuration,
)
from agents_factory.modules.agent_factory.publication_preview import (
    run_candidate_preview,
)
from agents_factory.modules.agent_factory.publication_tests import (
    CandidateTestResult,
    run_candidate_tests,
    test_result_satisfies_spec as satisfies_spec,
)
from agents_factory.modules.runtime.contracts import (
    AgentTurnResult,
    RuntimeToolCall,
    RuntimeUsage,
    ToolInvocationContext,
    TurnMessage,
)
from apps.backend.tests.unit.test_lead_capability import draft_and_knowledge
from apps.backend.tests.unit.agent_factory.test_onboarding_projection import spec


def candidate(enabled=True):
    draft, knowledge, _ = draft_and_knowledge(enabled)
    return spec(project_configuration(draft, knowledge, "a" * 64), knowledge.tenant_id)


class SimulationRuntime:
    def __init__(self, *, omit=False, external=False):
        self.calls, self.omit, self.external = [], omit, external

    async def run(self, turn):
        self.calls.append(turn)
        body = turn.messages[-1].text
        operations = []
        operation = (
            "SUPPRESS"
            if body.startswith("No guardes")
            else "CAPTURE"
            if "cotizar" in body
            else None
        )
        if operation and not self.omit:
            index = 1 if operation == "SUPPRESS" else 0
            tool = turn.tools[index]
            args = {
                "operation": operation,
                "evidence": [
                    {"message_id": str(turn.trace.inbound_message_id), "quote": body}
                ],
                **(
                    {"need_summary": "Interés en una solución"}
                    if operation == "CAPTURE"
                    else {}
                ),
            }
            await tool.handler(
                ToolInvocationContext(
                    turn.trace.tenant_id,
                    turn.trace.conversation_id,
                    turn.trace.inbound_message_id,
                    turn.trace.correlation_id,
                ),
                args,
            )
            operations = [
                RuntimeToolCall(tool.name, args, {"saved": True, "simulated": False})
            ]
        if self.external:
            operations = [RuntimeToolCall("crm.write", {}, {"simulated": True})]
        return AgentTurnResult(
            "Respuesta simulada",
            tuple(operations),
            RuntimeUsage(1, 1, 0, 1, 0, 2),
            None,
        )


async def test_preview_returns_server_validated_simulation_without_real_persistence(
    monkeypatch,
):
    from agents_factory.modules.leads.service import LeadCaptureService

    async def forbidden(*args, **kwargs):
        raise AssertionError("preview attempted persistence")

    monkeypatch.setattr(LeadCaptureService, "apply", forbidden)
    result = await run_candidate_preview(
        candidate(),
        (TurnMessage(uuid4(), "user", "Quiero cotizar un agente"),),
        SimulationRuntime(),
    )
    assert result.error_code is None
    assert len(result.lead_proposals) == 1
    assert result.lead_proposals[0].simulated is True
    assert result.lead_proposals[0].need_summary == "Interés en una solución"


async def test_negative_preview_and_external_tool_cannot_create_simulation():
    result = await run_candidate_preview(
        candidate(), (TurnMessage(uuid4(), "user", "Hola"),), SimulationRuntime()
    )
    assert result.response and not result.lead_proposals
    external = await run_candidate_preview(
        candidate(),
        (TurnMessage(uuid4(), "user", "Hola"),),
        SimulationRuntime(external=True),
    )
    assert external.error_code == "unsafe_test_output" and not external.lead_proposals


async def test_enabled_suite_has_nine_results_and_eight_model_calls():
    runtime = SimulationRuntime()
    version = candidate()
    result = await run_candidate_tests(version, runtime)
    assert result.schema_version == 2 and result.checks_passed
    assert len(result.scenarios) == 9 and len(runtime.calls) == 8
    assert satisfies_spec(result, version)
    interest = next(s for s in result.scenarios if s.key == "lead_interest")
    assert interest.lead_proposals[0].operation == "CAPTURE"
    refusal = next(s for s in result.scenarios if s.key == "lead_refusal")
    assert refusal.lead_proposals[0].operation == "SUPPRESS"


async def test_missing_capture_cannot_pass_enabled_suite():
    result = await run_candidate_tests(candidate(), SimulationRuntime(omit=True))
    assert not result.checks_passed
    assert not next(s for s in result.scenarios if s.key == "lead_interest").passed


async def test_legacy_results_are_backward_compatible_but_do_not_approve_new_capability():
    legacy = candidate(False)
    result = await run_candidate_tests(legacy, SimulationRuntime())
    assert result.schema_version == 1 and len(result.scenarios) == 6
    stored = CandidateTestResult.model_validate(result.model_dump(mode="json"))
    assert satisfies_spec(stored, legacy)
    assert not satisfies_spec(stored, candidate())
