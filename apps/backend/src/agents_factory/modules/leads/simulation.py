"""Pure preview projection. This module deliberately has no persistence imports."""

from typing import Literal

from agents_factory.modules.runtime.contracts import AgentTurnInput, AgentTurnResult
from .models import LeadProposal, parse_lead_proposal, validate_evidence
from .capability import LEAD_CAPTURE_TOOLS, lead_capture_enabled


class SimulatedLeadProposal(LeadProposal):
    simulated: Literal[True] = True


def simulated_proposals(
    turn: AgentTurnInput, result: AgentTurnResult
) -> list[SimulatedLeadProposal]:
    allowed = (
        {tool.name for tool in turn.tools} & LEAD_CAPTURE_TOOLS
        if lead_capture_enabled(turn.agent_spec)
        else set()
    )
    proposals: dict[str, LeadProposal] = {}
    for call in result.tool_calls:
        if call.tool_name not in allowed:
            raise ValueError("external or unauthorized preview operation")
        proposal = parse_lead_proposal(call.arguments)
        operation = (
            "CAPTURE" if call.tool_name == "lead_capture.propose" else "SUPPRESS"
        )
        if proposal.operation != operation or operation in proposals:
            raise ValueError("duplicate or mismatched preview operation")
        validate_evidence(proposal, turn.messages, turn.trace.inbound_message_id)
        proposals[operation] = proposal
    values = (
        [proposals["SUPPRESS"]] if "SUPPRESS" in proposals else list(proposals.values())
    )
    return [SimulatedLeadProposal(**proposal.model_dump()) for proposal in values]
