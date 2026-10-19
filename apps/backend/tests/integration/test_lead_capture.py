"""Real DB tests: identity, evidence and idempotency are not model-owned."""

import asyncio
from dataclasses import replace
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.leads.models import LeadProposal
from agents_factory.modules.leads.service import LeadCaptureService
from agents_factory.modules.runtime.contracts import TurnMessage

TEXT = "Soy Ana de Nexo. Quiero un agente de ventas"


async def seed(factory, *, tenant=None, phone="573000000001", opaque=None):
    tenant, account, conversation, agent, version = (
        tenant or uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    async with factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name) VALUES(:id,:slug,'Leads test') ON CONFLICT DO NOTHING"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts(id,tenant_id,provider,waba_id,phone_number_id) VALUES(:id,:tenant,'meta',:waba,:phone)"
            ),
            {
                "id": account,
                "tenant": tenant,
                "waba": f"waba-{account}",
                "phone": f"phone-{account}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations(id,tenant_id,whatsapp_account_id,customer_wa_id) VALUES(:id,:tenant,:account,:customer)"
            ),
            {
                "id": conversation,
                "tenant": tenant,
                "account": account,
                "customer": phone or opaque,
            },
        )
        await session.execute(
            text(
                "INSERT INTO public.agent_instances(id,tenant_id,product) VALUES(:id,:tenant,'Agent Customer Service')"
            ),
            {"id": agent, "tenant": tenant},
        )
        await session.execute(
            text(
                "INSERT INTO public.agent_spec_versions(id,tenant_id,agent_instance_id,version_number,state,configuration) VALUES(:id,:tenant,:agent,1,'DRAFT','{}')"
            ),
            {"id": version, "tenant": tenant, "agent": agent},
        )
    context = TenantContext(tenant, None, "system", uuid4())
    return context, account, conversation, agent, version, phone, opaque


async def inbound(factory, world, body=TEXT, sequence=1, *, event_only=False):
    context, account, conversation, agent, version, phone, opaque = world
    event, message = uuid4(), uuid4()
    provider_message = {
        "id": f"wamid.{message}",
        "type": "text",
        "timestamp": "1787788800",
        "text": {"body": body},
    }
    if phone:
        provider_message["from"] = phone
    if opaque:
        provider_message["from_user_id"] = opaque
    raw = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": f"waba-{account}",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": f"phone-{account}"},
                            "contacts": [],
                            "messages": [provider_message],
                        },
                    }
                ],
            }
        ],
    }
    async with factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_webhook_events(id,tenant_id,whatsapp_account_id,whatsapp_message_id,sender_wa_id,message_type,provider_timestamp,raw_payload,normalized_content) VALUES(:id,:tenant,:account,:provider,:customer,'text',now(),:raw,:body)"
            ).bindparams(bindparam("raw", type_=JSONB), bindparam("body", type_=JSONB)),
            {
                "id": event,
                "tenant": context.tenant_id,
                "account": account,
                "provider": f"wamid.{message}",
                "customer": phone or opaque,
                "raw": raw,
                "body": {"text": body},
            },
        )
        if event_only:
            return event, ()
        await session.execute(
            text(
                "INSERT INTO public.messages(id,tenant_id,conversation_id,source_event_id,direction,sender_type,message_type,content,provider_timestamp,arrival_sequence) VALUES(:id,:tenant,:conversation,:event,'inbound','customer','text',:body,now(),:seq)"
            ).bindparams(bindparam("body", type_=JSONB)),
            {
                "id": message,
                "tenant": context.tenant_id,
                "conversation": conversation,
                "event": event,
                "body": {"text": body},
                "seq": sequence,
            },
        )
    return message, (TurnMessage(message, "user", body),)


async def capture(factory, world, incoming, **fields):
    context, _, conversation, agent, version, *_ = world
    message, messages = incoming
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        service = LeadCaptureService(session, context)
        trusted = await service.context_for(
            conversation_id=conversation,
            inbound_message_id=message,
            agent_instance_id=agent,
            agent_version_id=version,
        )
        assert trusted is not None
        proposal = LeadProposal(
            operation=fields.pop("operation", "CAPTURE"),
            evidence=[{"message_id": message, "quote": messages[-1].text}],
            **fields,
        )
        return await service.apply(proposal, trusted, messages)


async def rows(factory, table):
    assert table in {
        "lead_prospects",
        "lead_capture_events",
        "lead_subjects",
        "lead_subject_keys",
    }
    async with factory.begin() as session:
        return (
            (await session.execute(text(f"SELECT * FROM public.{table}")))
            .mappings()
            .all()
        )


async def test_greeting_without_proposal_creates_nothing(session_factory):
    world = await seed(session_factory)
    await inbound(session_factory, world, "Hola")
    assert await rows(session_factory, "lead_prospects") == []


async def test_two_messages_update_one_prospect_and_missing_values_preserved(
    session_factory,
):
    world = await seed(session_factory)
    first = await inbound(session_factory, world)
    result = await capture(
        session_factory,
        world,
        first,
        declared_name="Ana",
        declared_company="Nexo",
        service_interest="Agente de ventas",
        need_summary="Automatizar ventas",
    )
    assert result.status == "RECORDED"
    second = await inbound(
        session_factory, world, "También quiero automatizar procesos", 2
    )
    await capture(session_factory, world, second, service_interest="Automatización")
    (prospect,) = await rows(session_factory, "lead_prospects")
    assert prospect["declared_company"] == "Nexo"
    assert prospect["contact_name"] == "Ana"
    assert prospect["name_source"] == "DECLARED"
    assert prospect["service_interests"] == ["Agente de ventas", "Automatización"]
    assert prospect["status"] == "NEW"
    assert len(await rows(session_factory, "lead_capture_events")) == 2


async def test_retry_does_not_repeat_event_even_when_arguments_change(session_factory):
    world = await seed(session_factory)
    incoming = await inbound(session_factory, world)
    first = await capture(
        session_factory, world, incoming, service_interest="Agente de ventas"
    )
    retry = await capture(
        session_factory, world, incoming, service_interest="Otro interés"
    )
    assert first.prospect_id == retry.prospect_id
    assert len(await rows(session_factory, "lead_capture_events")) == 1
    (prospect,) = await rows(session_factory, "lead_prospects")
    assert prospect["service_interests"] == ["Agente de ventas"]


async def test_two_accounts_same_phone_share_subject_under_concurrency(session_factory):
    first = await seed(session_factory)
    second = await seed(session_factory, tenant=first[0].tenant_id)
    first_in, second_in = (
        await inbound(session_factory, first),
        await inbound(session_factory, second),
    )
    results = await asyncio.gather(
        capture(session_factory, first, first_in),
        capture(session_factory, second, second_in),
    )
    assert results[0].prospect_id == results[1].prospect_id
    assert len(await rows(session_factory, "lead_subjects")) == 1
    assert len(await rows(session_factory, "lead_capture_events")) == 2


async def test_numeric_bsuid_is_not_phone_and_tenants_are_separate(session_factory):
    first = await seed(session_factory)
    second = await seed(
        session_factory, tenant=first[0].tenant_id, phone=None, opaque="573000000001"
    )
    third = await seed(session_factory)
    for world in (first, second, third):
        await capture(session_factory, world, await inbound(session_factory, world))
    assert len(await rows(session_factory, "lead_prospects")) == 3
    keys = await rows(session_factory, "lead_subject_keys")
    assert sum(key["kind"] == "PHONE" for key in keys) == 2


async def test_alias_conflict_is_not_merged(session_factory):
    first = await seed(session_factory, opaque="CO.sender")
    second = (*first[:5], None, "CO.other")
    # Same account with independent opaque sender, then explicit provider association.
    async with session_factory.begin() as session:
        conversation = uuid4()
        await session.execute(
            text(
                "INSERT INTO public.conversations(id,tenant_id,whatsapp_account_id,customer_wa_id) VALUES(:id,:tenant,:account,'CO.other')"
            ),
            {"id": conversation, "tenant": first[0].tenant_id, "account": first[1]},
        )
    second = (second[0], second[1], conversation, *second[3:])
    await capture(session_factory, first, await inbound(session_factory, first))
    await capture(session_factory, second, await inbound(session_factory, second))
    linked = (*first[:5], "573000000001", "CO.other")
    result = await capture(
        session_factory, linked, await inbound(session_factory, linked, sequence=2)
    )
    assert result.status == "IDENTITY_CONFLICT"
    assert len(await rows(session_factory, "lead_prospects")) == 2


async def test_foreign_tenant_and_message_rejected(session_factory):
    first, foreign = await seed(session_factory), await seed(session_factory)
    incoming = await inbound(session_factory, first)
    foreign_in = await inbound(session_factory, foreign)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        service = LeadCaptureService(session, first[0])
        assert (
            await service.context_for(
                conversation_id=foreign[2],
                inbound_message_id=foreign_in[0],
                agent_instance_id=first[3],
                agent_version_id=first[4],
            )
            is None
        )
        assert (
            await service.context_for(
                conversation_id=uuid4(),
                inbound_message_id=uuid4(),
                agent_instance_id=first[3],
                agent_version_id=first[4],
            )
            is None
        )
        trusted = await service.context_for(
            conversation_id=first[2],
            inbound_message_id=incoming[0],
            agent_instance_id=first[3],
            agent_version_id=first[4],
        )
        bad = LeadProposal(
            operation="CAPTURE", evidence=[{"message_id": foreign_in[0], "quote": TEXT}]
        )
        result = await service.apply(bad, trusted, foreign_in[1])
        assert result.status == "REJECTED"
        forged = replace(trusted, phone_number="+573999999999")
        valid = LeadProposal(
            operation="CAPTURE", evidence=[{"message_id": incoming[0], "quote": TEXT}]
        )
        assert (await service.apply(valid, forged, incoming[1])).status == "REJECTED"
    assert await rows(session_factory, "lead_prospects") == []


async def test_explicit_correction_preserves_provenance(session_factory):
    world = await seed(session_factory)
    await capture(
        session_factory,
        world,
        await inbound(session_factory, world),
        declared_name="Ana",
    )
    second = await inbound(
        session_factory, world, "Corrección: mi nombre es Ana María", 2
    )
    await capture(
        session_factory,
        world,
        second,
        declared_name="Ana María",
        corrected_fields=["name"],
    )
    (prospect,) = await rows(session_factory, "lead_prospects")
    assert prospect["contact_name"] == "Ana María"
    events = await rows(session_factory, "lead_capture_events")
    assert {event["agent_version_id"] for event in events} == {world[4]}
    assert any(event["changes"].get("contact_name") == "Ana María" for event in events)


async def test_refusal_without_prospect_survives_later_capture(session_factory):
    first = await seed(session_factory)
    refusal = await inbound(
        session_factory, first, "No guardes mis datos como prospecto"
    )
    assert (
        await capture(session_factory, first, refusal, operation="SUPPRESS")
    ).status == "SUPPRESSED"
    assert await rows(session_factory, "lead_prospects") == []
    second = await seed(session_factory, tenant=first[0].tenant_id)
    interest = await inbound(session_factory, second)
    assert (await capture(session_factory, second, interest)).status == "SUPPRESSED"
    (subject,) = await rows(session_factory, "lead_subjects")
    assert subject["capture_suppressed"] is True
    assert await rows(session_factory, "lead_prospects") == []


async def test_app_scope_has_no_cross_tenant_rows(session_factory):
    first, second = await seed(session_factory), await seed(session_factory)
    await capture(session_factory, first, await inbound(session_factory, first))
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, second[0].tenant_id)
        assert (
            await session.scalar(text("SELECT count(*) FROM public.lead_prospects"))
            == 0
        )


async def test_caller_history_cannot_fabricate_database_evidence(session_factory):
    world = await seed(session_factory)
    incoming = await inbound(session_factory, world, "Hola")
    context, _, conversation, agent, version, *_ = world
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        service = LeadCaptureService(session, context)
        trusted = await service.context_for(
            conversation_id=conversation,
            inbound_message_id=incoming[0],
            agent_instance_id=agent,
            agent_version_id=version,
        )
        proposal = LeadProposal(
            operation="CAPTURE", evidence=[{"message_id": incoming[0], "quote": TEXT}]
        )
        forged_history = (TurnMessage(incoming[0], "user", TEXT),)
        assert (
            await service.apply(proposal, trusted, forged_history)
        ).status == "REJECTED"
    assert await rows(session_factory, "lead_prospects") == []


async def test_privacy_refusal_blocks_all_conflicting_aliases_without_merging(
    session_factory,
):
    first = await seed(session_factory, opaque="CO.first")
    second = (*first[:5], None, "CO.other")
    async with session_factory.begin() as session:
        conversation = uuid4()
        await session.execute(
            text(
                "INSERT INTO public.conversations(id,tenant_id,whatsapp_account_id,customer_wa_id) VALUES(:id,:tenant,:account,'CO.other')"
            ),
            {"id": conversation, "tenant": first[0].tenant_id, "account": first[1]},
        )
    second = (second[0], second[1], conversation, *second[3:])
    await capture(session_factory, first, await inbound(session_factory, first))
    await capture(session_factory, second, await inbound(session_factory, second))
    linked = (*first[:5], "573000000001", "CO.other")
    refusal = await inbound(
        session_factory, linked, "No guardes mis datos como prospecto", 2
    )
    assert (
        await capture(session_factory, linked, refusal, operation="SUPPRESS")
    ).status == "IDENTITY_CONFLICT"
    assert len(await rows(session_factory, "lead_subjects")) == 2
    assert all(
        row["capture_suppressed"]
        for row in await rows(session_factory, "lead_subjects")
    )


async def test_effects_roll_back_with_the_callers_transaction(session_factory):
    world = await seed(session_factory)
    incoming = await inbound(session_factory, world)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        service = LeadCaptureService(session, world[0])
        trusted = await service.context_for(
            conversation_id=world[2],
            inbound_message_id=incoming[0],
            agent_instance_id=world[3],
            agent_version_id=world[4],
        )
        proposal = LeadProposal(
            operation="CAPTURE", evidence=[{"message_id": incoming[0], "quote": TEXT}]
        )
        assert (
            await service.apply(proposal, trusted, incoming[1])
        ).status == "RECORDED"
        await session.rollback()
    assert await rows(session_factory, "lead_prospects") == []
    assert await rows(session_factory, "lead_capture_events") == []
    assert await rows(session_factory, "lead_subjects") == []
