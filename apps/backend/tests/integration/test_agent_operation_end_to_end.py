from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text, bindparam
from sqlalchemy.dialects.postgresql import JSONB

from agents_factory.common.context import TenantContext
from agents_factory.modules.runtime.turn_service import (
    AgentTurnService,
    Milestone2AgentSpecProvider,
)
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.agent_factory.channel_provider import (
    ConversationAgentSpecProvider,
)
from agents_factory.modules.whatsapp.outbound_service import OutboundMessageService
from agents_factory.modules.whatsapp.contracts import ProviderMessageResult
from apps.backend.tests.integration.runtime.test_agent_turn import _FakeRuntime
from apps.backend.tests.integration.test_agent_operation_runtime import incoming
from apps.backend.tests.integration.test_agent_message_admission import (
    operation_world as _operation_world,
    change_state,
    build_operation_world,
)

operation_world = _operation_world


async def run_published(factory, world, message, runtime):
    operation = TenantContext(world[0].tenant_id, None, "system", uuid4())
    async with factory() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        provider = ConversationAgentSpecProvider(
            session,
            operation,
            message.conversation_id,
            Milestone2AgentSpecProvider(),
            code_digest="a" * 64,
        )
        result = await AgentTurnService(
            session=session,
            session_factory=factory,
            context=operation,
            runtime=runtime,
            agent_specs=provider,
            tools=RuntimeToolRegistry(()),
        ).process(
            conversation_id=message.conversation_id,
            inbound_message_id=message.message_id,
        )
        await session.commit()
        return result


@pytest.mark.asyncio
async def test_pause_during_snapshot_selection_never_starts_model(
    session_factory, operation_world
):
    world = operation_world
    message = await incoming(session_factory, world)
    snapshot = await Milestone2AgentSpecProvider().get_active(
        tenant_id=world[0].tenant_id
    )

    class Provider:
        async def get_active(self, *, tenant_id):
            await change_state(session_factory, world, False, 1)
            return snapshot

    runtime = _FakeRuntime()
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        result = await AgentTurnService(
            session=session,
            context=world[0],
            runtime=runtime,
            agent_specs=Provider(),
            tools=RuntimeToolRegistry(()),
        ).process(
            conversation_id=message.conversation_id,
            inbound_message_id=message.message_id,
        )
    assert result.status == "blocked_by_agent_operation"
    assert not runtime.turns


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timestamp", [None, "bad-date", "-1", {}, "99999999999999999999"]
)
async def test_signed_invalid_time_is_retained_without_automation(
    session_factory, operation_world, timestamp
):
    import json
    from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
    from agents_factory.modules.whatsapp.webhook import MetaWebhookProcessor
    from apps.backend.tests.integration.test_whatsapp_deduplication import (
        FIXTURE,
        APP_SECRET,
        _signature,
    )

    world = operation_world
    await change_state(session_factory, world, False, 1)
    await change_state(session_factory, world, True, 2)
    async with session_factory.begin() as session:
        account = (
            (
                await session.execute(
                    text(
                        "SELECT waba_id,phone_number_id FROM public.whatsapp_accounts WHERE id=:a"
                    ),
                    {"a": world[1]},
                )
            )
            .mappings()
            .one()
        )
    payload = json.loads(FIXTURE.read_bytes())
    entry = payload["entry"][0]
    entry["id"] = account["waba_id"]
    value = entry["changes"][0]["value"]
    value["metadata"]["phone_number_id"] = account["phone_number_id"]
    if timestamp is None:
        value["messages"][0].pop("timestamp")
    else:
        value["messages"][0]["timestamp"] = timestamp
    body = json.dumps(payload).encode()
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await MetaWebhookProcessor(
            session=session,
            provider=MetaCloudApiProvider(app_secret=SecretStr(APP_SECRET)),
        ).process(raw_body=body, signature=_signature(body), correlation_id=uuid4())
    async with session_factory.begin() as session:
        event = (
            await session.execute(
                text("SELECT normalized_content FROM public.whatsapp_webhook_events")
            )
        ).scalar_one()
        admission = (
            (
                await session.execute(
                    text("SELECT eligible,reason FROM public.agent_message_admissions")
                )
            )
            .mappings()
            .one()
        )
        assert event["_provider_timestamp_valid"] is False
        assert dict(admission) == {"eligible": False, "reason": "invalid_timestamp"}
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_contact_profiles")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_two_company_text_and_audio_flow_keeps_only_new_responses(
    session_factory, operation_world
):
    from agents_factory.modules.audio_ingestion.authorization import AudioAuthority
    from agents_factory.modules.audio_ingestion.service import AudioIngestionService
    from agents_factory.modules.audio_ingestion.models import (
        AudioInspection,
        AudioTranscript,
        TRANSCRIPTION_MODEL,
    )
    from agents_factory.modules.audio_ingestion.repository import AudioRepository
    from agents_factory.common.queue import JobEnvelope
    from apps.backend.tests.integration.audio_fixtures import audio_message

    first, other = operation_world, await build_operation_world(session_factory)
    runtime = _FakeRuntime()

    class Provider:
        def __init__(self):
            self.requests = []

        async def send_text(self, request):
            self.requests.append(request)
            return ProviderMessageResult(
                outcome="accepted", provider_message_id=f"sent.{len(self.requests)}"
            )

        async def send_template(self, request):
            raise AssertionError("unexpected template")

    transport = Provider()
    outbound = OutboundMessageService(
        session_factory=session_factory, context=first[0], provider=transport
    )
    old = await incoming(session_factory, first)
    ready = await run_published(session_factory, first, old, runtime)
    prepared = await outbound.prepare_text(message_id=ready.assistant_message_id)
    await change_state(session_factory, first, False, 1)
    assert (await outbound.send(prepared)).status == "BLOCKED"
    paused = await incoming(session_factory, first)
    assert (
        await run_published(session_factory, first, paused, runtime)
    ).status == "blocked_by_agent_operation"
    unaffected = await incoming(session_factory, other)
    assert (
        await run_published(session_factory, other, unaffected, runtime)
    ).status == "completed"
    await change_state(session_factory, first, True, 2)
    assert (await outbound.send(prepared)).status == "BLOCKED"
    assert (
        await run_published(session_factory, first, paused, runtime)
    ).status == "blocked_by_agent_operation"
    async with session_factory.begin() as session:
        version = await session.scalar(
            text(
                "SELECT version_id FROM public.account_agent_bindings WHERE whatsapp_account_id=:a"
            ),
            {"a": first[1]},
        )
    audio_world = (
        first[0],
        first[1],
        old.conversation_id,
        first[2],
        version,
        "573101234567",
        None,
    )
    voice = await audio_message(session_factory, audio_world, sequence=4)
    async with session_factory.begin() as session:
        source = (
            (
                await session.execute(
                    text(
                        "SELECT e.id,e.raw_payload,a.waba_id,a.phone_number_id FROM public.messages m JOIN public.whatsapp_webhook_events e ON e.id=m.source_event_id JOIN public.whatsapp_accounts a ON a.id=e.whatsapp_account_id WHERE m.id=:m"
                    ),
                    {"m": voice},
                )
            )
            .mappings()
            .one()
        )
        raw = source["raw_payload"]
        raw["entry"][0]["id"] = source["waba_id"]
        raw["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = source[
            "phone_number_id"
        ]
        await session.execute(
            text(
                "UPDATE public.whatsapp_webhook_events SET raw_payload=:raw WHERE id=:e"
            ).bindparams(bindparam("raw", type_=JSONB)),
            {"raw": raw, "e": source["id"]},
        )
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await AudioRepository(session, first[0]).enqueue(voice)
        job = await session.scalar(
            text(
                "SELECT id FROM public.outbox_jobs WHERE tenant_id=:t AND topic='whatsapp.audio.transcribe'"
            ),
            {"t": first[0].tenant_id},
        )

    class Download:
        async def download(self, source, destination):
            return SimpleNamespace(size_bytes=3, sha256="1" * 64)

    class Inspect:
        async def inspect(self, path):
            return AudioInspection("ogg", "opus", 1, 3)

    class Transcribe:
        async def transcribe(self, path, inspection):
            return AudioTranscript("Quiero conocer los servicios", TRANSCRIPTION_MODEL)

    authority = AudioAuthority(
        lambda session, context, conversation: ConversationAgentSpecProvider(
            session,
            context,
            conversation,
            Milestone2AgentSpecProvider(),
            code_digest="a" * 64,
        )
    )
    audio = AudioIngestionService(
        session_factory,
        downloader=Download(),
        inspector=Inspect(),
        transcriber=Transcribe(),
        authority=authority,
    )
    await audio.process(
        JobEnvelope(
            job, first[0].tenant_id, "whatsapp.audio.transcribe", old.conversation_id
        )
    )
    message = SimpleNamespace(conversation_id=old.conversation_id, message_id=voice)
    answered = await run_published(session_factory, first, message, runtime)
    assert answered.status == "completed"
    assert (
        await outbound.send(
            await outbound.prepare_text(message_id=answered.assistant_message_id)
        )
    ).status == "ACCEPTED"
    assert len(transport.requests) == 1
    assert transport.requests[0].whatsapp_account_id == first[1]
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.messages WHERE tenant_id=:t AND direction='inbound'"
                ),
                {"t": first[0].tenant_id},
            )
            == 3
        )
        assert (
            await session.scalar(
                text(
                    "SELECT status FROM public.whatsapp_audio_transcriptions WHERE inbound_message_id=:m"
                ),
                {"m": voice},
            )
            == "READY"
        )
