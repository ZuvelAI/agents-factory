from uuid import uuid4

import pytest
from sqlalchemy import text, bindparam
from sqlalchemy.dialects.postgresql import JSONB


@pytest.mark.asyncio
async def test_published_context_reaches_runtime_and_draft_changes_do_not_replace_it(
    session_factory,
):
    from test_agent_turn import _seed_inbound, _FakeRuntime
    from apps.backend.tests.integration.agent_factory.test_publication_candidates import (
        configuration,
        context,
    )
    from apps.backend.tests.integration.agent_factory.test_channel_publication import (
        prepare_reviewed,
    )
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )
    from agents_factory.modules.agent_factory.channel_provider import (
        ConversationAgentSpecProvider,
    )
    from agents_factory.modules.runtime.turn_service import (
        AgentTurnService,
        Milestone2AgentSpecProvider,
    )
    from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry

    operation, conversation, message = await _seed_inbound(session_factory)
    tenant = operation.tenant_id
    config = configuration()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenant_onboarding_configs(tenant_id,revision,configuration) VALUES(:tenant,1,:config)"
            ).bindparams(bindparam("config", type_=JSONB)),
            {"tenant": tenant, "config": config.model_dump(mode="json")},
        )
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET health_status='HEALTHY' WHERE tenant_id=:tenant"
            ),
            {"tenant": tenant},
        )
        selected = await session.scalar(
            text("SELECT whatsapp_account_id FROM public.conversations WHERE id=:id"),
            {"id": conversation},
        )
    administrator = context(tenant)
    candidate, run = await prepare_reviewed(session_factory, tenant, administrator)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await PanelPublicationService(
            session, administrator, code_digest="a" * 64
        ).publish(
            version_id=candidate.id,
            whatsapp_account_id=selected,
            expected_revision=1,
            test_run_id=run.id,
            expected_binding_revision=0,
        )
        await session.execute(
            text(
                "UPDATE public.tenant_onboarding_configs SET revision=2,configuration=jsonb_set(configuration,'{agent,greeting}','\"Nuevo saludo sin publicar\"') WHERE tenant_id=:tenant"
            ),
            {"tenant": tenant},
        )
    runtime = _FakeRuntime()
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        provider = ConversationAgentSpecProvider(
            session,
            operation,
            conversation,
            Milestone2AgentSpecProvider(),
            code_digest="a" * 64,
        )
        result = await AgentTurnService(
            session=session,
            context=operation,
            runtime=runtime,
            agent_specs=provider,
            tools=RuntimeToolRegistry(()),
        ).process(conversation_id=conversation, inbound_message_id=message)
        assert result.status == "completed"
    assert len(runtime.turns) == 1
    prompt = runtime.turns[0].agent_spec.instructions
    assert "Bienvenido a Zuvel" in prompt and "Ofrecemos servicios digitales" in prompt
    assert "Nuevo saludo sin publicar" not in prompt
    assert runtime.turns[0].agent_spec.id == candidate.id
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        compatible = await ConversationAgentSpecProvider(
            session,
            operation,
            conversation,
            Milestone2AgentSpecProvider(),
            code_digest="c" * 64,
            compatible_versions={candidate.id: "a" * 64},
        ).get_active(tenant_id=tenant)
        assert compatible.id == candidate.id
        for digest, versions in (
            (None, {candidate.id: "a" * 64}),
            ("c" * 64, {candidate.id: "b" * 64}),
            ("c" * 64, {uuid4(): "a" * 64}),
        ):
            with pytest.raises(RuntimeError, match="integrity"):
                await ConversationAgentSpecProvider(
                    session,
                    operation,
                    conversation,
                    Milestone2AgentSpecProvider(),
                    code_digest=digest,
                    compatible_versions=versions,
                ).get_active(tenant_id=tenant)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        with pytest.raises(RuntimeError, match="integrity"):
            await ConversationAgentSpecProvider(
                session,
                operation,
                conversation,
                Milestone2AgentSpecProvider(),
                code_digest="c" * 64,
            ).get_active(tenant_id=tenant)
    next_message = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.conversations SET control_state='HUMAN_ACTIVE' WHERE id=:id"
            ),
            {"id": conversation},
        )
        await session.execute(
            text(
                "INSERT INTO public.messages(id,tenant_id,conversation_id,direction,sender_type,message_type,content,provider_timestamp,arrival_sequence) "
                "VALUES(:id,:tenant,:conversation,'inbound','customer','text','{\"text\":\"Otra consulta\"}',now(),100)"
            ),
            {"id": next_message, "tenant": tenant, "conversation": conversation},
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        provider = ConversationAgentSpecProvider(
            session,
            operation,
            conversation,
            Milestone2AgentSpecProvider(),
            code_digest="a" * 64,
        )
        blocked = await AgentTurnService(
            session=session,
            context=operation,
            runtime=runtime,
            agent_specs=provider,
            tools=RuntimeToolRegistry(()),
        ).process(conversation_id=conversation, inbound_message_id=next_message)
        assert blocked.status == "blocked_by_conversation_control"
    assert len(runtime.turns) == 1


@pytest.mark.asyncio
async def test_unbound_account_uses_legacy_but_missing_conversation_does_not(
    session_factory,
):
    from test_agent_turn import _seed_inbound
    from agents_factory.modules.agent_factory.channel_provider import (
        ConversationAgentSpecProvider,
    )
    from agents_factory.modules.runtime.turn_service import Milestone2AgentSpecProvider

    operation, conversation, _ = await _seed_inbound(session_factory)
    legacy = Milestone2AgentSpecProvider()
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        loaded = await ConversationAgentSpecProvider(
            session, operation, conversation, legacy, code_digest=None
        ).get_active(tenant_id=operation.tenant_id)
        assert loaded.version == "m2-baseline-v1"
        assert (
            await ConversationAgentSpecProvider(
                session, operation, uuid4(), legacy, code_digest=None
            ).get_active(tenant_id=operation.tenant_id)
            is None
        )
        with pytest.raises(RuntimeError, match="tenant"):
            await ConversationAgentSpecProvider(
                session, operation, conversation, legacy, code_digest=None
            ).get_active(tenant_id=uuid4())
