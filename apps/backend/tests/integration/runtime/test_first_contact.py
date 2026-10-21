"""Real DB regressions: presentation is account/contact history, not process memory."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from test_agent_turn import _FakeRuntime, _SpecProvider, _seed_inbound
from apps.backend.tests.unit.agent_factory.test_onboarding_projection import (
    inputs,
    project,
    spec,
)
from agents_factory.modules.runtime.turn_service import AgentTurnService
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry

WELCOME = "¡Hola! 👋 Bienvenido a Zuvel.\n\n• *Agentes de inteligencia artificial*.\n\n¿Qué proceso quieres mejorar?"
ANSWER = "Hola, ya reviso tu solicitud."


def configured_snapshot(tenant):
    configuration, knowledge = inputs()
    configuration.agent.greeting = WELCOME
    return spec(project(configuration, knowledge), tenant).to_runtime_snapshot(
        active=True
    )


async def reply(factory, context, conversation, inbound, snapshot):
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        result = await AgentTurnService(
            session=session,
            context=context,
            runtime=_FakeRuntime(),
            agent_specs=_SpecProvider(snapshot),
            tools=RuntimeToolRegistry(()),
        ).process(conversation_id=conversation, inbound_message_id=inbound)
    async with factory.begin() as session:
        body = await session.scalar(
            text("SELECT content->>'text' FROM public.messages WHERE id=:id"),
            {"id": result.assistant_message_id},
        )
    return result, body


@pytest.mark.asyncio
async def test_new_contact_gets_exact_welcome_before_the_question_answer(
    session_factory,
):
    context, conversation, inbound = await _seed_inbound(session_factory)
    _, body = await reply(
        session_factory,
        context,
        conversation,
        inbound,
        configured_snapshot(context.tenant_id),
    )
    assert body == WELCOME + "\n\n" + ANSWER


@pytest.mark.asyncio
async def test_retry_and_new_service_do_not_repeat_welcome(session_factory):
    context, conversation, inbound = await _seed_inbound(session_factory)
    snapshot = configured_snapshot(context.tenant_id)
    first, body = await reply(session_factory, context, conversation, inbound, snapshot)
    repeated, replay_body = await reply(
        session_factory, context, conversation, inbound, snapshot
    )
    assert body.startswith(WELCOME)
    assert (
        repeated.status == "already_processed"
        and repeated.assistant_message_id == first.assistant_message_id
    )
    assert replay_body == body
    async with session_factory.begin() as session:
        later = uuid4()
        await session.execute(
            text(
                "INSERT INTO public.messages(id,tenant_id,conversation_id,direction,sender_type,message_type,content,provider_timestamp,arrival_sequence) VALUES(:id,:tenant,:conversation,'inbound','customer','text','{\"text\":\"Necesito un agente\"}',now(),3)"
            ),
            {"id": later, "tenant": context.tenant_id, "conversation": conversation},
        )
    from apps.backend.tests.integration.operation_fixtures import admit_fixture_message

    async with session_factory.begin() as session:
        await admit_fixture_message(session, later)
    _, second = await reply(
        session_factory,
        context,
        conversation,
        later,
        replace(snapshot, id=uuid4(), version="updated"),
    )
    assert second == ANSWER


@pytest.mark.asyncio
@pytest.mark.parametrize("archive", [False, True])
async def test_existing_live_or_imported_history_never_receives_welcome(
    session_factory, archive
):
    context, conversation, inbound = await _seed_inbound(session_factory)
    async with session_factory.begin() as session:
        if archive:
            await session.execute(
                text(
                    "INSERT INTO public.whatsapp_history_messages(id,tenant_id,whatsapp_account_id,provider_message_id,customer_wa_id,direction,content,provider_timestamp) SELECT :id,tenant_id,whatsapp_account_id,'historic-first-contact',customer_wa_id,'inbound','{\"text\":\"Consulta anterior\"}',now()-interval '1 day' FROM public.conversations WHERE id=:conversation"
                ),
                {"id": uuid4(), "conversation": conversation},
            )
        else:
            await session.execute(
                text("UPDATE public.messages SET arrival_sequence=2 WHERE id=:id"),
                {"id": inbound},
            )
            await session.execute(
                text(
                    "INSERT INTO public.messages(id,tenant_id,conversation_id,direction,sender_type,message_type,content,provider_timestamp,arrival_sequence) VALUES(:id,:tenant,:conversation,'outbound','ai','text','{\"text\":\"Saludo anterior\"}',now()-interval '1 day',1)"
                ),
                {
                    "id": uuid4(),
                    "tenant": context.tenant_id,
                    "conversation": conversation,
                },
            )
    _, body = await reply(
        session_factory,
        context,
        conversation,
        inbound,
        configured_snapshot(context.tenant_id),
    )
    assert body == ANSWER


@pytest.mark.asyncio
async def test_old_unanswered_contact_is_not_reclassified_after_activation(
    session_factory,
):
    context, conversation, inbound = await _seed_inbound(session_factory)
    snapshot = replace(
        configured_snapshot(context.tenant_id),
        first_contact_since=datetime.now(UTC) + timedelta(seconds=1),
    )
    _, body = await reply(session_factory, context, conversation, inbound, snapshot)
    assert body == ANSWER


@pytest.mark.asyncio
async def test_imported_address_book_contact_is_not_new(session_factory):
    context, conversation, inbound = await _seed_inbound(session_factory)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_contacts(id,tenant_id,whatsapp_account_id,customer_wa_id,provider_timestamp) SELECT :id,tenant_id,whatsapp_account_id,customer_wa_id,now() FROM public.conversations WHERE id=:conversation"
            ),
            {"id": uuid4(), "conversation": conversation},
        )
    _, body = await reply(
        session_factory,
        context,
        conversation,
        inbound,
        configured_snapshot(context.tenant_id),
    )
    assert body == ANSWER


@pytest.mark.asyncio
async def test_later_inbound_can_receive_welcome_when_first_turn_failed(
    session_factory,
):
    context, conversation, first = await _seed_inbound(session_factory)
    snapshot = configured_snapshot(context.tenant_id)

    class FailingRuntime:
        async def run(self, turn):
            raise RuntimeError("simulated provider failure")

    with pytest.raises(RuntimeError, match="simulated provider failure"):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await AgentTurnService(
                session=session,
                context=context,
                runtime=FailingRuntime(),
                agent_specs=_SpecProvider(snapshot),
                tools=RuntimeToolRegistry(()),
            ).process(conversation_id=conversation, inbound_message_id=first)
    later = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.messages(id,tenant_id,conversation_id,direction,sender_type,message_type,content,provider_timestamp,arrival_sequence) VALUES(:id,:tenant,:conversation,'inbound','customer','text','{\"text\":\"¿Sigues ahí?\"}',now(),2)"
            ),
            {"id": later, "tenant": context.tenant_id, "conversation": conversation},
        )
    from apps.backend.tests.integration.operation_fixtures import admit_fixture_message

    async with session_factory.begin() as session:
        await admit_fixture_message(session, later)
    _, second_body = await reply(
        session_factory, context, conversation, later, snapshot
    )
    assert second_body == WELCOME + "\n\n" + ANSWER
    _, first_body = await reply(session_factory, context, conversation, first, snapshot)
    assert first_body == ANSWER
