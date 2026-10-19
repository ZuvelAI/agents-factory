"""Validate server evidence and apply prepared effects in the caller's transaction."""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.runtime.contracts import TurnMessage

from .identity import LeadIdentityResolver
from .models import (
    LeadCaptureOutcome,
    LeadEvidence,
    LeadProposal,
    TrustedLeadContext,
    validate_evidence,
)
from .repository import LeadRepository


class LeadCaptureService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.repository = LeadRepository(session, context)

    async def context_for(
        self,
        *,
        conversation_id: UUID,
        inbound_message_id: UUID,
        agent_instance_id: UUID,
        agent_version_id: UUID,
    ) -> TrustedLeadContext | None:
        return await self.repository.load_context(
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
            agent_instance_id=agent_instance_id,
            agent_version_id=agent_version_id,
        )

    async def apply(
        self,
        proposal: LeadProposal,
        trusted: TrustedLeadContext,
        messages: tuple[TurnMessage, ...],
    ) -> LeadCaptureOutcome:
        repo = self.repository
        if (
            trusted.tenant_id != repo.context.tenant_id
            or trusted.agent_instance_id is None
            or trusted.agent_version_id is None
        ):
            return LeadCaptureOutcome("REJECTED")
        canonical = await self.context_for(
            conversation_id=trusted.conversation_id,
            inbound_message_id=trusted.inbound_message_id,
            agent_instance_id=trusted.agent_instance_id,
            agent_version_id=trusted.agent_version_id,
        )
        if canonical != trusted:
            return LeadCaptureOutcome("REJECTED")
        try:
            proposal = LeadProposal.model_validate(proposal.model_dump())
            validate_evidence(proposal, messages, trusted.inbound_message_id)
            # The model/caller's history is not authoritative for stored evidence.
            stored = await repo.evidence_messages(
                trusted, tuple(e.message_id for e in proposal.evidence)
            )
            validate_evidence(proposal, stored, trusted.inbound_message_id)
        except (ValueError, ValidationError):
            return LeadCaptureOutcome("REJECTED")
        resolution = await LeadIdentityResolver(repo).resolve(trusted)
        if resolution.conflicted:
            if proposal.operation == "SUPPRESS":
                for subject_id in resolution.conflict_subject_ids:
                    await repo.lock_subject(subject_id)
                    await self._suppress_subject(subject_id, trusted.inbound_message_id)
            await self._event(
                trusted,
                proposal,
                "CONFLICT",
                None,
                {"capture_suppressed": True}
                if proposal.operation == "SUPPRESS"
                else {},
            )
            return LeadCaptureOutcome("IDENTITY_CONFLICT")
        subject = resolution.subject_id
        if subject is None:
            return LeadCaptureOutcome("REJECTED")
        previous = await repo.previous_event(trusted.inbound_message_id)
        if previous and (
            previous["operation"] != "CAPTURE" or proposal.operation != "SUPPRESS"
        ):
            if previous["operation"] == "SUPPRESS":
                return LeadCaptureOutcome("SUPPRESSED", previous["prospect_id"])
            if previous["operation"] == "CONFLICT":
                return LeadCaptureOutcome("IDENTITY_CONFLICT")
            return LeadCaptureOutcome("RECORDED", previous["prospect_id"])
        suppressed = await repo.lock_subject(subject)
        existing = await repo.prospect(subject)
        prospect_id = existing["id"] if existing else None
        if proposal.operation == "SUPPRESS":
            await self._suppress_subject(subject, trusted.inbound_message_id)
            await self._event(trusted, proposal, "SUPPRESS", prospect_id, {})
            return LeadCaptureOutcome("SUPPRESSED", prospect_id)
        if suppressed:
            return LeadCaptureOutcome("SUPPRESSED", prospect_id)

        values: dict[str, object] = {
            "contact_name": existing["contact_name"] if existing else None,
            "name_source": existing["name_source"] if existing else None,
            "contact_username": existing["contact_username"] if existing else None,
            "declared_company": existing["declared_company"] if existing else None,
            "need_summary": existing["need_summary"] if existing else None,
            "summary_source": existing["summary_source"] if existing else None,
        }
        if proposal.declared_name and (
            values["name_source"] != "DECLARED" or "name" in proposal.corrected_fields
        ):
            values.update(contact_name=proposal.declared_name, name_source="DECLARED")
        elif not values["contact_name"] and trusted.profile_name:
            values.update(contact_name=trusted.profile_name, name_source="PROFILE")
        if trusted.username:
            values["contact_username"] = trusted.username
        if proposal.declared_company and (
            not values["declared_company"] or "company" in proposal.corrected_fields
        ):
            values["declared_company"] = proposal.declared_company
        if proposal.need_summary:
            values.update(
                need_summary=proposal.need_summary, summary_source="SYNTHESIZED"
            )
        interests = list(existing["service_interests"]) if existing else []
        if proposal.service_interest and proposal.service_interest.casefold() not in {
            item.casefold() for item in interests
        }:
            interests.append(proposal.service_interest)
        values["service_interests"] = interests
        changes = {
            key: value
            for key, value in values.items()
            if value is not None and (not existing or value != existing[key])
        }
        prospect_id = prospect_id or new_uuid7()
        await repo.execute(
            "INSERT INTO public.lead_prospects(id,tenant_id,subject_id,contact_name,name_source,contact_username,declared_company,service_interests,need_summary,summary_source,first_conversation_id,last_conversation_id) "
            "VALUES(:id,:tenant,:subject,:contact_name,:name_source,:contact_username,:declared_company,:service_interests,:need_summary,:summary_source,:conversation,:conversation) "
            "ON CONFLICT(tenant_id,subject_id) DO UPDATE SET contact_name=excluded.contact_name,name_source=excluded.name_source,contact_username=excluded.contact_username,declared_company=excluded.declared_company,service_interests=excluded.service_interests,need_summary=excluded.need_summary,summary_source=excluded.summary_source,last_conversation_id=excluded.last_conversation_id,updated_at=now()",
            {
                "id": prospect_id,
                "subject": subject,
                "conversation": trusted.conversation_id,
                **values,
            },
            json_fields=("service_interests",),
        )
        await self._event(trusted, proposal, "CAPTURE", prospect_id, changes)
        return LeadCaptureOutcome("RECORDED", prospect_id)

    async def suppress(
        self, trusted: TrustedLeadContext, evidence: tuple[LeadEvidence, ...]
    ) -> LeadCaptureOutcome:
        proposal = LeadProposal(operation="SUPPRESS", evidence=evidence)
        messages = await self.repository.evidence_messages(
            trusted, tuple(e.message_id for e in evidence)
        )
        return await self.apply(proposal, trusted, messages)

    async def _suppress_subject(self, subject_id: UUID, message_id: UUID) -> None:
        await self.repository.suppress_subject(subject_id, message_id)

    async def _event(
        self,
        trusted: TrustedLeadContext,
        proposal: LeadProposal,
        operation: str,
        prospect_id: UUID | None,
        changes: dict[str, object],
    ) -> None:
        await self.repository.execute(
            "INSERT INTO public.lead_capture_events(id,tenant_id,prospect_id,conversation_id,inbound_message_id,agent_instance_id,agent_version_id,operation,evidence,changes) "
            "VALUES(:id,:tenant,:prospect,:conversation,:inbound,:agent,:version,:operation,:evidence,:changes) ON CONFLICT(tenant_id,inbound_message_id,operation) DO NOTHING",
            {
                "id": new_uuid7(),
                "prospect": prospect_id,
                "conversation": trusted.conversation_id,
                "inbound": trusted.inbound_message_id,
                "agent": trusted.agent_instance_id,
                "version": trusted.agent_version_id,
                "operation": operation,
                "evidence": [e.model_dump(mode="json") for e in proposal.evidence],
                "changes": changes,
            },
            json_fields=("evidence", "changes"),
        )
