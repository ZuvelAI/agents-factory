from sqlalchemy import text

from apps.backend.tests.handoff_support import HandoffHarness
from apps.backend.tests.integration.runtime.test_agent_turn import (
    _FakeRuntime,
    _SpecProvider,
    _seed_inbound,
    _spec,
)
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.runtime.turn_service import AgentTurnService
from agents_factory.modules.whatsapp.contracts import ProviderMessageResult
from agents_factory.modules.whatsapp.outbound_service import OutboundMessageService


class Provider:
    calls = 0

    async def send_text(self, request):
        self.calls += 1
        return ProviderMessageResult("accepted", "wamid.handoff-fixture")


async def run_turn(sessions, context, conversation_id, inbound_id, runtime):
    async with sessions.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        return await AgentTurnService(
            session=session,
            context=context,
            runtime=runtime,
            agent_specs=_SpecProvider(_spec(context.tenant_id)),
            tools=RuntimeToolRegistry(()),
        ).process(conversation_id=conversation_id, inbound_message_id=inbound_id)


async def test_human_takeover_during_generation_suppresses_persistence_and_audits(
    conversation_session_factory, clean_conversation_tables
):
    sessions = conversation_session_factory
    context, conversation_id, inbound_id = await _seed_inbound(sessions)
    h = await HandoffHarness.create(sessions, context, conversation_id)

    class RacingRuntime(_FakeRuntime):
        async def run(self, turn):
            await h.human_event(await h.request())
            return await super().run(turn)

    runtime = RacingRuntime()
    result = await run_turn(sessions, context, conversation_id, inbound_id, runtime)
    assert result.status == "blocked_by_conversation_control"
    assert len(runtime.turns) == 1
    assert (
        await run_turn(sessions, context, conversation_id, inbound_id, runtime)
    ).status == "blocked_by_conversation_control"
    assert len(runtime.turns) == 1
    async with sessions.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.messages WHERE tenant_id=:tenant AND sender_type='ai'"
                ),
                {"tenant": context.tenant_id},
            )
            == 0
        )
        stages = (
            (
                await session.execute(
                    text(
                        "SELECT payload->>'stage' FROM public.audit_events WHERE tenant_id=:tenant AND event_type='agent.turn.authority_suppressed'"
                    ),
                    {"tenant": context.tenant_id},
                )
            )
            .scalars()
            .all()
        )
        assert set(stages) == {"before_generation", "after_generation"}


async def test_delayed_ai_send_and_waiting_receipt_are_blocked_after_human_activation(
    conversation_session_factory, clean_conversation_tables
):
    sessions = conversation_session_factory
    context, conversation_id, inbound_id = await _seed_inbound(sessions)
    h = await HandoffHarness.create(sessions, context, conversation_id)
    result = await run_turn(
        sessions, context, conversation_id, inbound_id, _FakeRuntime()
    )
    provider = Provider()
    outbound = OutboundMessageService(
        session_factory=sessions, context=context, provider=provider
    )
    ai_outbound = await outbound.prepare_text(message_id=result.assistant_message_id)
    record = await h.request()
    receipt = await outbound.prepare_text(message_id=record.notice_message_id)
    await h.human_event(record)
    assert (await outbound.send(ai_outbound)).status == "BLOCKED"
    assert (await outbound.send(receipt)).status == "BLOCKED"
    assert provider.calls == 0
    async with sessions.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events WHERE tenant_id=:tenant AND event_type='whatsapp.outbound.authority_suppressed'"
                ),
                {"tenant": context.tenant_id},
            )
            == 2
        )


async def test_waiting_receipt_is_single_non_ai_notice(
    conversation_session_factory, clean_conversation_tables
):
    sessions = conversation_session_factory
    context, conversation_id, _ = await _seed_inbound(sessions)
    h = await HandoffHarness.create(sessions, context, conversation_id)
    record = await h.request()
    provider = Provider()
    outbound = OutboundMessageService(
        session_factory=sessions, context=context, provider=provider
    )
    notice = await outbound.prepare_text(message_id=record.notice_message_id)
    assert (await outbound.send(notice)).status == "ACCEPTED"
    assert (await outbound.send(notice)).status == "ACCEPTED"
    assert provider.calls == 1
