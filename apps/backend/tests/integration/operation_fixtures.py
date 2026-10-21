"""Explicit synthetic operational authority for tests with injected runtimes.

These identities do not claim real publication: publication integration tests
install their own version first. All admission decisions use production code.
"""

from uuid import uuid4
from sqlalchemy import text
from agents_factory.common.context import TenantContext


async def admit_fixture_event(session, tenant, account, event):
    from agents_factory.modules.agent_operations.admission import admit_event
    from agents_factory.database import set_tenant_context
    await set_tenant_context(session,tenant)

    binding = (
        (
            await session.execute(
                text(
                    "SELECT agent_instance_id,version_id FROM public.account_agent_bindings WHERE tenant_id=:t AND whatsapp_account_id=:a"
                ),
                {"t": tenant, "a": account},
            )
        )
        .mappings()
        .one_or_none()
    )
    if binding is None:
        agent, version = uuid4(), uuid4()
        await session.execute(
            text(
                "INSERT INTO public.agent_instances(id,tenant_id,product) VALUES(:id,:t,'Agent Customer Service')"
            ),
            {"id": agent, "t": tenant},
        )
        await session.execute(
            text(
                "INSERT INTO public.agent_spec_versions(id,tenant_id,agent_instance_id,version_number,state,configuration) VALUES(:id,:t,:a,1,'DRAFT','{}')"
            ),
            {"id": version, "t": tenant, "a": agent},
        )
        await session.execute(
            text(
                "INSERT INTO public.account_agent_bindings(tenant_id,whatsapp_account_id,agent_instance_id,version_id,revision) VALUES(:t,:a,:agent,:v,1)"
            ),
            {"t": tenant, "a": account, "agent": agent, "v": version},
        )
    else:
        agent = binding["agent_instance_id"]
    await session.execute(
        text(
            "INSERT INTO public.agent_operation_states(tenant_id,agent_instance_id) VALUES(:t,:a) ON CONFLICT DO NOTHING"
        ),
        {"t": tenant, "a": agent},
    )
    timestamp = await session.scalar(
        text(
            "SELECT provider_timestamp FROM public.whatsapp_webhook_events WHERE tenant_id=:t AND id=:e"
        ),
        {"t": tenant, "e": event},
    )
    return await admit_event(
        session,
        TenantContext(tenant, None, "system", uuid4()),
        event_id=event,
        account_id=account,
        provider_timestamp=timestamp,
    )


async def admit_fixture_message(session, message):
    row = (
        (
            await session.execute(
                text(
                    "SELECT m.tenant_id,m.source_event_id,c.whatsapp_account_id,c.customer_wa_id,"
                    "m.provider_timestamp,m.content FROM public.messages m JOIN public.conversations c "
                    "ON (c.tenant_id,c.id)=(m.tenant_id,m.conversation_id) WHERE m.id=:m"
                ),
                {"m": message},
            )
        )
        .mappings()
        .one()
    )
    event = row["source_event_id"] or uuid4()
    if row["source_event_id"] is None:
        from sqlalchemy import bindparam
        from sqlalchemy.dialects.postgresql import JSONB

        await session.execute(
            text(
                "INSERT INTO public.whatsapp_webhook_events(id,tenant_id,whatsapp_account_id,whatsapp_message_id,sender_wa_id,message_type,normalized_content,provider_timestamp,raw_payload) "
                "VALUES(:e,:t,:a,:p,:customer,'text',:body,:at,'{}')"
            ).bindparams(bindparam("body", type_=JSONB)),
            {
                "e": event,
                "t": row["tenant_id"],
                "a": row["whatsapp_account_id"],
                "p": f"wamid.fixture.{event}",
                "customer": row["customer_wa_id"],
                "body": row["content"],
                "at": row["provider_timestamp"],
            },
        )
        await session.execute(
            text("UPDATE public.messages SET source_event_id=:e WHERE id=:m"),
            {"e": event, "m": message},
        )
    return await admit_fixture_event(
        session, row["tenant_id"], row["whatsapp_account_id"], event
    )
