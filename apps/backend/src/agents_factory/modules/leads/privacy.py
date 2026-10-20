"""Conservative direct-refusal guard; not a commercial-interest classifier."""

import re
import unicodedata
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from .identity import LeadIdentityResolver
from .repository import LeadRepository
from agents_factory.modules.audio_ingestion.repository import AudioRepository

_DIRECT_REFUSAL = re.compile(
    r"(?:por favor[, ]+)?(?:no (?:guardes|registres|almacenes) mis datos(?: como prospecto)?"
    r"|no quiero que (?:guardes|registres|almacenes) mis datos(?: como prospecto)?"
    r"|(?:please[, ]+)?(?:do not|don't) (?:save|store|record) my (?:data|details)(?: as a lead)?)"
    r"[.!]?"
)


def explicit_capture_refusal(text: str) -> bool:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    return _DIRECT_REFUSAL.fullmatch(" ".join(normalized.split())) is not None


async def persist_direct_refusal(
    session: AsyncSession,
    context: TenantContext,
    *,
    conversation_id: UUID,
    inbound_message_id: UUID,
    body: str,
) -> None:
    if not explicit_capture_refusal(body):
        return
    repo = LeadRepository(session, context)
    eligible = await repo.execute(
        "SELECT EXISTS(SELECT 1 FROM public.lead_subjects WHERE tenant_id=:tenant) OR EXISTS("
        "SELECT 1 FROM public.account_agent_bindings b JOIN public.agent_spec_versions v "
        "ON v.tenant_id=b.tenant_id AND v.agent_instance_id=b.agent_instance_id AND v.id=b.version_id "
        "WHERE b.tenant_id=:tenant AND v.state='PRODUCTION' "
        'AND v.configuration->\'capabilities\' @> \'[{"name":"lead_capture","version":"1.0.0"}]\'::jsonb '
        "AND v.configuration->'permitted_tools' @> '[\"lead_capture.propose\",\"lead_capture.suppress\"]'::jsonb)",
        {},
    )
    if not eligible.scalar_one():
        return
    # A direct customer's refusal has no agent author; do not forge attribution.
    trusted = await repo.load_context(
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        agent_instance_id=None,
        agent_version_id=None,
    )
    if trusted is None:
        return
    kind = (
        await repo.execute(
            "SELECT message_type FROM public.messages WHERE tenant_id=:tenant AND id=:id",
            {"id": inbound_message_id},
        )
    ).scalar_one_or_none()
    if kind == "audio":
        ready = await AudioRepository(session, context).read_ready(
            (inbound_message_id,)
        )
        if inbound_message_id not in ready or ready[inbound_message_id].text != body:
            return
    resolution = await LeadIdentityResolver(repo).resolve(trusted)
    subject_ids = (
        resolution.conflict_subject_ids
        if resolution.conflicted
        else (resolution.subject_id,)
    )
    for subject_id in subject_ids:
        if subject_id is not None:
            await repo.lock_subject(subject_id)
            await repo.suppress_subject(subject_id, inbound_message_id)
    await AuditService(session).record(
        context=context,
        event_type="lead.direct_capture_refusal",
        entity_type="message",
        entity_id=inbound_message_id,
        payload={
            "conversation_id": str(conversation_id),
            "identity_conflict": resolution.conflicted,
        },
    )
