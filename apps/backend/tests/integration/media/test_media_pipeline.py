from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from apps.backend.tests.media_support import MediaProvider, Scanner
from apps.backend.tests.handoff_support import activate_verified_handoff
from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, require_platform_admin
from agents_factory.common.queue import JobEnvelope
from agents_factory.database import set_tenant_context
from agents_factory.modules.media.contracts import MediaError
from agents_factory.modules.media.service import MediaService, observation_text
from agents_factory.modules.media.router import router
from agents_factory.modules.media.storage import (
    LocalPrivateMediaStore,
    MediaAccessSigner,
)
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agent_worker.jobs import handle_whatsapp_inbound
from agents_factory.modules.runtime.turn_service import _RuntimeTurnRepository


@pytest.fixture
async def media_world(session_factory, tmp_path):
    tenant, account, conversation = uuid4(), uuid4(), uuid4()
    context = TenantContext(tenant, uuid4(), "system", uuid4())
    clock = [datetime.now(UTC)]
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name) VALUES (:id,:slug,'Task27')"
            ),
            {"id": tenant, "slug": f"media-{tenant}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts(id,tenant_id,provider,waba_id,phone_number_id) VALUES (:id,:tenant,'meta','27',:phone)"
            ),
            {"id": account, "tenant": tenant, "phone": str(uuid4().int)},
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations(id,tenant_id,whatsapp_account_id,customer_wa_id) VALUES (:id,:tenant,:account,'573000000027')"
            ),
            {"id": conversation, "tenant": tenant, "account": account},
        )
    count = [0]

    async def message(kind, content):
        count[0] += 1
        identifier = uuid4()
        async with session_factory.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO public.messages(id,tenant_id,conversation_id,direction,sender_type,message_type,content,provider_timestamp,arrival_sequence) VALUES (:id,:tenant,:conversation,'inbound','customer',:kind,:content,now(),:seq)"
                ).bindparams(bindparam("content", type_=JSONB)),
                {
                    "id": identifier,
                    "tenant": tenant,
                    "conversation": conversation,
                    "kind": kind,
                    "content": content,
                    "seq": count[0],
                },
            )
        return identifier

    provider, scanner = MediaProvider(), Scanner()
    service = MediaService(
        sessions=session_factory,
        provider=provider,
        scanner=scanner,
        storage=LocalPrivateMediaStore(tmp_path / "private-media"),
        signer=MediaAccessSigner(
            ResolvedSecret(b"fixture-signing-material-for-task27")
        ),
        now=lambda: clock[0],
    )
    return SimpleNamespace(
        context=context,
        account=account,
        conversation=conversation,
        clock=clock,
        message=message,
        service=service,
        provider=provider,
        scanner=scanner,
        sessions=session_factory,
    )


async def test_modalities_replay_evidence_access_and_retention_without_openai(
    media_world,
):
    world = media_world
    service, context = world.service, world.context
    image_id = await world.message("image", {"id": "1", "mime_type": "image/png"})
    first, second = await asyncio.gather(
        service.process(context=context, message_id=image_id),
        service.process(context=context, message_id=image_id),
    )
    assert first == second and first.status == "PENDING_PROVIDER"
    repeated_message = await world.message("image", {"id": "1"})
    assert await service.process(context=context, message_id=repeated_message) == first
    assert world.provider.calls == ["1"]
    results = [first]
    for kind, content, expected in (
        ("audio", {"id": "2"}, "PENDING_PROVIDER"),
        ("document", {"id": "3"}, "READY"),
        ("video", {"id": "4"}, "HUMAN_REVIEW"),
        ("location", {"latitude": 4.71, "longitude": -74.07}, "READY"),
        (
            "contacts",
            {
                "contacts": [
                    {
                        "name": {"formatted_name": "Fixture"},
                        "phones": [{"phone": "+573000000027"}],
                    }
                ]
            },
            "READY",
        ),
        ("text", {"text": "Hola"}, "READY"),
    ):
        result = await service.process(
            context=context, message_id=await world.message(kind, content)
        )
        assert result.status == expected
        assert result.identity_level_delta == 0 and result.response_modality == "text"
        if kind == "document":
            assert "Order evidence 27" in result.text
            assert "Untrusted customer media" in observation_text(
                {"media_observation": result.model_dump(mode="json")}
            )
        results.append(result)
    owner = "573000000027"
    assert await service.allowed(
        context=context, customer_ref=owner, evidence_id=first.evidence_id
    )
    assert not await service.allowed(
        context=context, customer_ref="other", evidence_id=first.evidence_id
    )
    foreign = replace(context, tenant_id=uuid4())
    assert not await service.allowed(
        context=foreign, customer_ref=owner, evidence_id=first.evidence_id
    )
    with pytest.raises(MediaError):
        await service.process(context=foreign, message_id=image_id)
    url = await service.signed_access(
        context=context, customer_ref=owner, evidence_id=first.evidence_id
    )
    query = parse_qs(urlsplit(url).query)
    app = FastAPI()
    app.include_router(router)
    app.state.media_service = service
    app.dependency_overrides[require_platform_admin] = lambda: AdminPrincipal(
        context.actor_id, uuid4()
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://local.test"
    ) as client:
        response = await client.get(url)
        assert (
            response.status_code == 200
            and response.content == world.provider.files["1"][0]
        )
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert (
            await client.get(
                url.replace(str(context.tenant_id), str(foreign.tenant_id))
            )
        ).status_code == 404
    args = dict(
        context=context,
        customer_ref=owner,
        evidence_id=first.evidence_id,
        expires=int(query["expires"][0]),
        signature=query["signature"][0],
    )
    assert await service.read_signed(**args) == world.provider.files["1"][0]
    with pytest.raises(MediaError):
        await service.read_signed(**{**args, "customer_ref": "other"})
    with pytest.raises(MediaError):
        await service.read_signed(**{**args, "context": foreign})
    world.clock[0] += timedelta(seconds=61)
    with pytest.raises(MediaError):
        await service.read_signed(**args)
    await service.delete(context=context, evidence_id=first.evidence_id)
    assert (
        await service.process(context=context, message_id=image_id)
    ).status == "DELETED"
    assert world.provider.calls == ["1", "2", "3", "4"]
    world.clock[0] += timedelta(days=91)
    assert await service.purge_expired(context=context) == 3
    assert not [path for path in service.storage.root.rglob("*") if path.is_file()]
    assert not await service.allowed(
        context=context, customer_ref=owner, evidence_id=results[1].evidence_id
    )
    async with world.sessions.begin() as session:
        await set_tenant_context(session, context.tenant_id)
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.media_evidence WHERE tenant_id=:id"),
                {"id": context.tenant_id},
            )
            == 4
        )


async def test_quarantine_corruption_crash_and_human_control_ingest(media_world):
    world = media_world
    service, context = world.service, world.context
    world.scanner.result = "UNAVAILABLE"
    message = await world.message("image", {"id": "1"})
    result = await service.process(context=context, message_id=message)
    assert result.status == "QUARANTINED"
    with pytest.raises(MediaError):
        await service.signed_access(
            context=context, customer_ref="573000000027", evidence_id=result.evidence_id
        )
    world.scanner.result = "CLEAN"
    result = await service.process(
        context=context, message_id=message, retry_pending=True
    )
    assert result.status == "PENDING_PROVIDER" and world.provider.calls == ["1"]
    world.provider.files["3"] = (b"%PDF-1.7\nnot a PDF\n%%EOF", "application/pdf")
    malformed = await service.process(
        context=context, message_id=await world.message("document", {"id": "3"})
    )
    assert malformed.status == "FAILED"
    assert (await service._get(context, malformed.evidence_id)).storage_key
    world.provider.error = asyncio.CancelledError()
    interrupted = await world.message("audio", {"id": "2"})
    with pytest.raises(asyncio.CancelledError):
        await service.process(context=context, message_id=interrupted)
    world.provider.error = None
    assert (
        await service.process(context=context, message_id=interrupted)
    ).reason_code == "media_processing_interrupted"
    assert world.provider.calls.count("2") == 1
    interrupted_record = await service._get(
        context,
        (await service.process(context=context, message_id=interrupted)).evidence_id,
    )
    # Simulate the separate file-write/metadata-commit crash window, then purge
    # that exact object even when the receipt lacks its content digest.
    await service.storage.put(
        tenant_id=context.tenant_id,
        media_id=interrupted_record.id,
        content=b"orphan fixture",
    )
    await service.delete(context=context, evidence_id=interrupted_record.id)
    assert not list(
        (
            service.storage.root / str(context.tenant_id) / str(interrupted_record.id)
        ).iterdir()
    )
    world.scanner.result = "INFECTED"
    infected = await service.process(
        context=context, message_id=await world.message("video", {"id": "4"})
    )
    assert infected.status == "QUARANTINED"
    assert not await service.allowed(
        context=context, customer_ref="573000000027", evidence_id=infected.evidence_id
    )
    # Actual inbound worker path preserves evidence with human control active.
    world.scanner.result = "CLEAN"
    world.provider.files["5"] = world.provider.files["1"]
    event_id = uuid4()
    await activate_verified_handoff(world.sessions, context, world.conversation)
    async with world.sessions.begin() as session:
        await set_tenant_context(session, context.tenant_id)
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_webhook_events(id,tenant_id,whatsapp_account_id,whatsapp_message_id,sender_wa_id,message_type,provider_timestamp,raw_payload,normalized_content) VALUES (:id,:tenant,:account,:provider,'573000000027','image',now(),'{}','{\"id\":\"5\"}')"
            ),
            {
                "id": event_id,
                "tenant": context.tenant_id,
                "account": world.account,
                "provider": str(event_id),
            },
        )
    await handle_whatsapp_inbound(
        envelope=JobEnvelope(
            uuid4(), context.tenant_id, "whatsapp.inbound.received", event_id
        ),
        database=SimpleNamespace(session_factory=world.sessions),
        media=service,
    )
    async with world.sessions.begin() as session:
        await set_tenant_context(session, context.tenant_id)
        raw = await session.scalar(
            text(
                "SELECT o.observation FROM public.media_observations o JOIN public.messages m ON m.tenant_id=o.tenant_id AND m.id=o.id WHERE m.source_event_id=:id"
            ),
            {"id": event_id},
        )
        assert raw["status"] == "PENDING_PROVIDER"
        original = await session.scalar(
            text("SELECT content FROM public.messages WHERE source_event_id=:id"),
            {"id": event_id},
        )
        assert original == {"id": "5"}
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE tenant_id=:id AND topic='agent.turn'"
                ),
                {"id": context.tenant_id},
            )
            == 0
        )


async def test_runtime_reads_separate_observations_without_mutating_messages(
    media_world,
):
    world = media_world
    identifier = await world.message(
        "location", {"latitude": 4.71, "longitude": -74.07}
    )
    await world.service.process(context=world.context, message_id=identifier)
    async with world.sessions.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        loaded = await _RuntimeTurnRepository(session).load(
            context=world.context,
            conversation_id=world.conversation,
            inbound_message_id=identifier,
        )
        assert loaded.inbound_message.role == "user"
        assert "Untrusted customer media" in loaded.inbound_message.text
        assert "4.71" in loaded.inbound_message.text
        original = await session.scalar(
            text("SELECT content FROM public.messages WHERE id=:id"), {"id": identifier}
        )
        assert original == {"latitude": 4.71, "longitude": -74.07}
