from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from apps.backend.tests.integration.runtime.test_agent_turn import _seed_inbound
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.observability.retention import (
    RetentionPolicy,
    RetentionService,
)


async def test_tenant_retention_minimizes_only_expired_classes_and_preserves_other_tenant(
    session_factory,
):
    first, conversation, inbound = await _seed_inbound(session_factory)
    other, _, other_inbound = await _seed_inbound(session_factory)
    context = replace(first, actor_id=new_uuid7(), actor_type="system")
    trace_message, fresh_message = new_uuid7(), new_uuid7()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "GRANT agents_factory_retention TO CURRENT_USER WITH INHERIT FALSE, SET TRUE"
            )
        )
        await session.execute(
            text(
                "UPDATE public.messages SET created_at=now()-interval '8 days', runtime_metadata=jsonb_build_object('tool_calls','synthetic sensitive tool output','model','fixture','usage',jsonb_build_object('total_tokens',3)) WHERE id=:id"
            ),
            {"id": inbound},
        )
        await session.execute(
            text(
                "UPDATE public.whatsapp_webhook_events SET received_at=now()-interval '8 days' WHERE tenant_id=:tenant"
            ),
            {"tenant": first.tenant_id},
        )
        for identifier, age in ((trace_message, 4), (fresh_message, 1)):
            await session.execute(
                text(
                    "INSERT INTO public.messages(id,tenant_id,conversation_id,direction,sender_type,message_type,content,provider_timestamp,arrival_sequence,created_at,runtime_metadata) SELECT :id,tenant_id,conversation_id,'inbound','customer','text',content,provider_timestamp,:sequence,now()-make_interval(days=>:age),jsonb_build_object('tool_calls','synthetic trace','usage',jsonb_build_object('total_tokens',3)) FROM public.messages WHERE id=:source"
                ),
                {
                    "id": identifier,
                    "sequence": 2 if age == 4 else 3,
                    "age": age,
                    "source": inbound,
                },
            )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        assert (
            await RetentionService.configure(
                session,
                context=replace(context, actor_type="platform_admin"),
                policy=RetentionPolicy(conversation_days=7, trace_days=2),
                expected_revision=0,
            )
            == 1
        )
        assert (
            await RetentionService.configure(
                session,
                context=replace(context, actor_type="platform_admin"),
                policy=RetentionPolicy(conversation_days=7, trace_days=2),
                expected_revision=1,
            )
            == 2
        )
    # Trace eligibility does NOT authorize erasing still-current conversation text.
    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_retention"))
            await set_tenant_context(session, first.tenant_id)
            await session.execute(
                text("UPDATE public.messages SET content='{}' WHERE id=:id"),
                {"id": trace_message},
            )
    service = RetentionService(session_factory)
    counts = await service.run(context=context)
    assert counts["conversation_content"] == 1
    assert counts["detailed_traces"] == 2
    assert counts["webhook_content"] == 1
    assert not any((await service.run(context=context)).values())
    async with session_factory.begin() as session:
        rows = {
            row.id: row
            for row in (
                await session.execute(
                    text("SELECT id,content,runtime_metadata FROM public.messages")
                )
            ).all()
        }
        assert rows[inbound].content == {}
        assert (
            rows[trace_message].content
            and "tool_calls" not in rows[trace_message].runtime_metadata
        )
        assert rows[inbound].runtime_metadata["usage"]["total_tokens"] == 3
        assert "tool_calls" in rows[fresh_message].runtime_metadata
        assert rows[other_inbound].content
        payload = await session.scalar(
            text(
                "SELECT payload FROM public.audit_events WHERE event_type='retention.batch_completed'"
            )
        )
        assert set(payload) == {"counts"} and "synthetic" not in str(payload)
        role = (
            await session.execute(
                text(
                    "SELECT rolsuper,rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname='agents_factory_retention'"
                )
            )
        ).one()
        assert role == (False, False, False)


async def test_action_audit_retention_deletes_due_records_without_rewriting_history(
    session_factory,
):
    context, conversation, _ = await _seed_inbound(session_factory)
    context = replace(context, actor_id=new_uuid7(), actor_type="system")
    action_id, audit_id = new_uuid7(), new_uuid7()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "GRANT agents_factory_retention TO CURRENT_USER WITH INHERIT FALSE, SET TRUE"
            )
        )
        await session.execute(
            text(
                "INSERT INTO public.actions(id,tenant_id,conversation_id,customer_ref,capability,action_type,risk,required_identity_level,achieved_identity_level,parameters,parameter_digest,confirmation_required,approval_required,connector_binding_id,connector_name,state,created_at,updated_at) VALUES (:id,:tenant,:conversation,'synthetic-customer','orders','orders.get_status','LOW',0,0,'{}',:digest,false,false,:binding,'woocommerce','REQUESTED',now()-interval '400 days',now()-interval '400 days')"
            ),
            {
                "id": action_id,
                "tenant": context.tenant_id,
                "conversation": conversation,
                "binding": new_uuid7(),
                "digest": "0" * 64,
            },
        )
        for state in ("IDENTITY_VERIFIED", "CONFIRMED", "EXECUTING", "SUCCEEDED"):
            await session.execute(
                text(
                    "UPDATE public.actions SET state=:state,execution_attempts=CASE WHEN :state='EXECUTING' THEN 1 ELSE execution_attempts END WHERE id=:id"
                ),
                {"id": action_id, "state": state},
            )
        await session.execute(
            text(
                "INSERT INTO public.action_events(id,tenant_id,action_id,version,to_state,event_type,payload,created_at) VALUES (:id,:tenant,:action,1,'SUCCEEDED','fixture','{}',now()-interval '400 days')"
            ),
            {"id": new_uuid7(), "tenant": context.tenant_id, "action": action_id},
        )
        await session.execute(
            text(
                "INSERT INTO public.audit_events(id,tenant_id,actor_type,event_type,entity_type,entity_id,correlation_id,occurred_at) VALUES (:id,:tenant,'system','fixture','action',:action,:correlation,now()-interval '400 days')"
            ),
            {
                "id": audit_id,
                "tenant": context.tenant_id,
                "action": action_id,
                "correlation": new_uuid7(),
            },
        )
    # Ordinary admins cannot assume the cleanup role or erase audit history.
    async with session_factory.begin() as session:
        assert not await session.scalar(
            text(
                "SELECT pg_has_role('agents_factory_admin','agents_factory_retention','MEMBER')"
            )
        )
    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_retention"))
            await set_tenant_context(session, context.tenant_id)
            await session.execute(
                text("UPDATE public.actions SET updated_at=now() WHERE id=:id"),
                {"id": action_id},
            )
    counts = await RetentionService(session_factory).run(context=context)
    assert (
        counts["actions"] == 1
        and counts["action_events"] == 1
        and counts["audit_records"] == 1
    )
    assert not any(
        (await RetentionService(session_factory).run(context=context)).values()
    )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.actions WHERE id=:id"),
                {"id": action_id},
            )
            == 0
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events WHERE event_type='conversation.message.received'"
                )
            )
            == 1
        )
