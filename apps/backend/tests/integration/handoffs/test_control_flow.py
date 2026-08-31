from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from apps.backend.tests.handoff_support import HandoffHarness, Surface
from apps.backend.tests.integration.runtime.test_agent_turn import _seed_inbound
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.handoffs.models import HandoffError, HumanResponseSurface


async def test_verified_control_replay_end_and_next_inbound(
    session_factory, clean_foundation_tables
):
    context, conversation_id, inbound_id = await _seed_inbound(session_factory)
    h = await HandoffHarness.create(session_factory, context, conversation_id)
    request = await h.request()
    assert request.status == "REQUESTED"
    assert (await h.request()).id == request.id
    active = await h.human_event(request)
    assert active.status == "ACTIVE"
    assert (await h.human_event(request)).event_sequence == 0
    with pytest.raises(HandoffError):
        await h.human_event(request, sequence=1, tenant_id=new_uuid7())
    ended = await h.human_event(request, sequence=2, kind="END")
    assert ended.status == "CLOSED"
    assert (await h.human_event(request, sequence=3)).status == "CLOSED"
    # A fresh verified customer event reopens under the existing session policy.
    event_id = new_uuid7()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_webhook_events (id,tenant_id,whatsapp_account_id,whatsapp_message_id,sender_wa_id,message_type,provider_timestamp,raw_payload,normalized_content) "
                "SELECT :id,tenant_id,whatsapp_account_id,:wamid,sender_wa_id,message_type,now(),raw_payload,normalized_content FROM public.whatsapp_webhook_events WHERE tenant_id=:tenant LIMIT 1"
            ),
            {"id": event_id, "wamid": str(event_id), "tenant": context.tenant_id},
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        result = await ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        ).ingest(event_id)
    assert result.control_state.value == "AI_ACTIVE"
    assert result.response_queued


async def test_unverified_api_only_denied_and_eligible_coexistence_allowed(
    session_factory, clean_foundation_tables
):
    context, conversation_id, _ = await _seed_inbound(session_factory)
    surface = Surface()
    surface.surface = HumanResponseSurface.WHATSAPP_COEXISTENCE
    with pytest.raises(HandoffError):
        await HandoffHarness.create(
            session_factory, context, conversation_id, surface=surface
        )
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET mode='COEXISTENCE',coexistence_eligibility='ELIGIBLE',health_status='HEALTHY',verified_at=now() WHERE tenant_id=:tenant"
            ),
            {"tenant": context.tenant_id},
        )
    h = await HandoffHarness.create(
        session_factory, context, conversation_id, surface=surface
    )
    surface.verified = False
    with pytest.raises(HandoffError):
        await h.request()
    surface.verified = True
    assert (await h.request()).status == "REQUESTED"


async def test_inactivity_uses_latest_activity_and_tenant_timeout(
    session_factory, clean_foundation_tables
):
    context, conversation_id, _ = await _seed_inbound(session_factory)
    h = await HandoffHarness.create(session_factory, context, conversation_id)
    record = await h.request()
    await h.human_event(record)
    h.clock += timedelta(hours=11)
    assert not await h.service.close_if_inactive(
        context=h.context, handoff_id=record.id
    )
    await h.human_event(record, kind="ACTIVITY", sequence=1)
    h.clock += timedelta(hours=2)
    assert not await h.service.close_if_inactive(
        context=h.context, handoff_id=record.id
    )
    h.clock += timedelta(hours=10)
    assert await h.service.close_if_inactive(context=h.context, handoff_id=record.id)
    assert not await h.service.close_if_inactive(
        context=h.context, handoff_id=record.id
    )


async def test_old_transition_api_cannot_enable_unverified_handoff(
    session_factory, clean_foundation_tables
):
    context, conversation_id, _ = await _seed_inbound(session_factory)
    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await ConversationService(
                session=session,
                context=context,
                awaiting_human_policy=AwaitingHumanPolicy.SILENT,
            ).request_handoff(conversation_id=conversation_id, reason="unverified")
