"""Isolated model preview: no customer persistence, tools or outbound effects."""

from typing import Literal, Self
from dataclasses import replace
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .models import AgentSpec
from agents_factory.modules.leads.runtime_tools import lead_tools_for_turn
from agents_factory.modules.leads.simulation import (
    SimulatedLeadProposal,
    simulated_proposals,
)
from agents_factory.modules.runtime.contracts import (
    AgentRuntime,
    AgentTurnInput,
    RuntimeTraceMetadata,
    TurnMessage,
)


class PreviewMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def user_input_limit(self) -> Self:
        if self.role == "user" and len(self.text) > 2000:
            raise ValueError("user input exceeds preview limit")
        return self


class PreviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    response: str | None = Field(default=None, min_length=1, max_length=8000)
    error_code: str | None = Field(default=None, max_length=100)
    lead_proposals: list[SimulatedLeadProposal] = Field(
        default_factory=list, max_length=1
    )

    @model_validator(mode="after")
    def exactly_one_result(self) -> Self:
        if (self.response is None) == (self.error_code is None):
            raise ValueError("preview requires response or error")
        if self.error_code and self.lead_proposals:
            raise ValueError("failed preview cannot contain simulated capture")
        return self


async def run_candidate_preview(
    spec: AgentSpec, messages: tuple[TurnMessage, ...], runtime: AgentRuntime
) -> PreviewResult:
    turn = AgentTurnInput(
        agent_spec=spec.to_runtime_snapshot(active=True),
        messages=messages,
        tools=(),
        trace=RuntimeTraceMetadata(
            tenant_id=spec.tenant_id,
            conversation_id=uuid4(),
            inbound_message_id=messages[-1].id,
            correlation_id=uuid4(),
            agent_spec_id=spec.version_id,
            agent_spec_digest=spec.digest(),
        ),
    )
    turn = replace(turn, tools=lead_tools_for_turn(turn, simulation=True))
    try:
        answer = await runtime.run(turn)
        if len(answer.output_text) > 8000 or "[PLATFORM SAFETY" in answer.output_text:
            return PreviewResult(error_code="unsafe_test_output")
        try:
            proposals = simulated_proposals(turn, answer)
        except ValueError:
            return PreviewResult(error_code="unsafe_test_output")
        return PreviewResult(response=answer.output_text, lead_proposals=proposals)
    except Exception:
        return PreviewResult(error_code="preview_generation_failed")
