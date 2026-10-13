from uuid import uuid4

import pytest

from agents_factory.modules.agent_factory.models import AgentSpec
from agents_factory.modules.runtime.contracts import AgentTurnResult, RuntimeUsage


@pytest.mark.asyncio
async def test_candidate_checks_run_without_customer_delivery_or_tools():
    from agents_factory.modules.agent_factory.publication_tests import (
        run_candidate_tests,
    )
    from agents_factory.modules.agent_factory.models import AgentSpecConfiguration

    configuration = AgentSpecConfiguration.model_validate(
        {
            "product_version": "1",
            "persona": {
                "version": "1",
                "instructions": "Atiende para Zuvel",
                "business_name": "Zuvel",
            },
            "policy": {"name": "standard", "version": "1"},
            "identity_policy": {"name": "standard", "version": "1"},
            "approval_routes": {"name": "standard", "version": "1"},
            "knowledge": {"name": "manual", "version": "1", "digest": "b" * 64},
            "human_operations": {"version": "1", "handoff_enabled": False},
            "code_digest": "a" * 64,
        }
    )
    spec = AgentSpec(
        tenant_id=uuid4(),
        agent_instance_id=uuid4(),
        version_id=uuid4(),
        version_number=1,
        configuration=configuration,
    )
    turns = []

    class Runtime:
        async def run(self, turn):
            turns.append(turn)
            return AgentTurnResult(
                output_text="Respuesta para revisión humana",
                tool_calls=(),
                usage=RuntimeUsage(1, 1, 0, 1, 0, 2),
                provider_response_id=None,
            )

    result = await run_candidate_tests(spec, Runtime())
    assert len(result.scenarios) == 6
    assert len(turns) == 5
    assert all(
        turn.tools == () and turn.trace.tenant_id == spec.tenant_id for turn in turns
    )
    assert result.checks_passed
    assert result.scenarios[-1].key == "human_control"
    assert result.scenarios[-1].passed


@pytest.mark.asyncio
async def test_runtime_generation_failure_cannot_pass_tests():
    from agents_factory.modules.agent_factory.publication_tests import (
        run_candidate_tests,
    )
    from agents_factory.modules.runtime.openai_adapter import AgentRuntimeError
    from agents_factory.modules.agent_factory.models import AgentSpecConfiguration

    config = AgentSpecConfiguration.model_validate(
        {
            "product_version": "1",
            "persona": {"version": "1", "instructions": "Zuvel"},
            "policy": {"name": "x", "version": "1"},
            "identity_policy": {"name": "x", "version": "1"},
            "approval_routes": {"name": "x", "version": "1"},
            "knowledge": {"name": "x", "version": "1", "digest": "b" * 64},
            "human_operations": {"version": "1"},
            "code_digest": "a" * 64,
        }
    )
    spec = AgentSpec(
        tenant_id=uuid4(),
        agent_instance_id=uuid4(),
        version_id=uuid4(),
        version_number=1,
        configuration=config,
    )

    class Runtime:
        async def run(self, turn):
            raise AgentRuntimeError("runtime_provider_error", retryable=True)

    result = await run_candidate_tests(spec, Runtime())
    assert not result.checks_passed
    assert all(
        s.error_code == "runtime_provider_error" and s.response is None
        for s in result.scenarios[:5]
    )
