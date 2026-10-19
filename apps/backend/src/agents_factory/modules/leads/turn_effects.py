"""Recheck published authority, then apply validated effects in the reply transaction."""

from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.account_lifecycle import lock_account_lifecycle
from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.models import AgentSpec
from agents_factory.modules.runtime.contracts import AgentTurnInput, AgentTurnResult
from agents_factory.modules.runtime.openai_adapter import AgentRuntimeError
from agents_factory.modules.whatsapp.outbound_service import lock_conversation_dispatch

from .capability import LEAD_CAPTURE_TOOLS, LEAD_CAPTURE_VERSION, lead_capture_enabled
from .models import (
    LeadCaptureOutcome,
    LeadProposal,
    validate_evidence,
    parse_lead_proposal,
)
from .service import LeadCaptureService


class LeadAuthorityChanged(AgentRuntimeError):
    def __init__(self) -> None:
        super().__init__("lead_authority_changed", retryable=True)


@dataclass(frozen=True, slots=True)
class LeadTurnAuthority:
    account_id: UUID
    customer_wa_id: str
    agent_instance_id: UUID
    version_id: UUID
    revision: int


class LeadTurnEffects:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session, self.context = session, context
        self._locked: LeadTurnAuthority | None = None

    async def prepare(self, turn: AgentTurnInput) -> LeadTurnAuthority:
        if turn.trace.tenant_id != self.context.tenant_id or not lead_capture_enabled(
            turn.agent_spec
        ):
            raise LeadAuthorityChanged
        await set_tenant_context(self.session, self.context.tenant_id)
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT c.whatsapp_account_id,c.customer_wa_id,b.agent_instance_id,b.version_id,b.revision,v.compiled_spec,v.compiled_digest "
                        "FROM public.conversations c JOIN public.whatsapp_accounts a ON a.tenant_id=c.tenant_id AND a.id=c.whatsapp_account_id "
                        "JOIN public.account_agent_bindings b ON b.tenant_id=c.tenant_id AND b.whatsapp_account_id=a.id "
                        "JOIN public.agent_spec_versions v ON v.tenant_id=b.tenant_id AND v.agent_instance_id=b.agent_instance_id AND v.id=b.version_id "
                        "WHERE c.tenant_id=:tenant AND c.id=:conversation AND a.status='active' AND v.state='PRODUCTION'"
                    ),
                    {
                        "tenant": self.context.tenant_id,
                        "conversation": turn.trace.conversation_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or row["version_id"] != turn.agent_spec.id
            or row["compiled_digest"] != turn.agent_spec.digest
        ):
            raise LeadAuthorityChanged
        try:
            stored = AgentSpec.model_validate(row["compiled_spec"])
        except ValidationError:
            raise LeadAuthorityChanged from None
        if (
            stored.digest() != turn.agent_spec.digest
            or not any(
                ref.name == "lead_capture" and ref.version == LEAD_CAPTURE_VERSION
                for ref in stored.configuration.capabilities
            )
            or stored.tenant_id != self.context.tenant_id
            or stored.agent_instance_id != row["agent_instance_id"]
            or stored.version_id != row["version_id"]
            or not lead_capture_enabled(stored.to_runtime_snapshot(active=True))
        ):
            raise LeadAuthorityChanged
        return LeadTurnAuthority(
            row["whatsapp_account_id"],
            row["customer_wa_id"],
            row["agent_instance_id"],
            row["version_id"],
            row["revision"],
        )

    async def lock_current(
        self, turn: AgentTurnInput, expected: LeadTurnAuthority
    ) -> None:
        await lock_conversation_dispatch(
            self.session,
            tenant_id=self.context.tenant_id,
            account_id=expected.account_id,
            customer_wa_id=expected.customer_wa_id,
        )
        await lock_account_lifecycle(
            self.session, self.context.tenant_id, expected.account_id
        )
        if await self.prepare(turn) != expected:
            raise LeadAuthorityChanged
        self._locked = expected

    async def apply(
        self, turn: AgentTurnInput, result: AgentTurnResult
    ) -> tuple[LeadCaptureOutcome, ...]:
        if self._locked is None or await self.prepare(turn) != self._locked:
            raise LeadAuthorityChanged
        calls = [
            call
            for call in result.tool_calls
            if call.tool_name.startswith("lead_capture.")
        ]
        if not calls:
            return ()
        allowed = {tool.name for tool in turn.tools} & LEAD_CAPTURE_TOOLS
        proposals: dict[str, LeadProposal] = {}
        for call in calls:
            if call.tool_name not in allowed:
                raise ValueError("lead operation not authorized")
            proposal = parse_lead_proposal(call.arguments)
            expected = (
                "CAPTURE" if call.tool_name == "lead_capture.propose" else "SUPPRESS"
            )
            if proposal.operation != expected or expected in proposals:
                raise ValueError("lead operation duplicated or mismatched")
            validate_evidence(proposal, turn.messages, turn.trace.inbound_message_id)
            proposals[expected] = proposal
        # A refusal is the only applied operation if both tools were called.
        proposal = proposals.get("SUPPRESS") or proposals["CAPTURE"]
        service = LeadCaptureService(self.session, self.context)
        trusted = await service.context_for(
            conversation_id=turn.trace.conversation_id,
            inbound_message_id=turn.trace.inbound_message_id,
            agent_instance_id=self._locked.agent_instance_id,
            agent_version_id=self._locked.version_id,
        )
        if trusted is None:
            raise ValueError("lead provider evidence unavailable")
        outcome = await service.apply(proposal, trusted, turn.messages)
        if outcome.status == "REJECTED":
            raise ValueError("lead evidence rejected")
        return (outcome,)
