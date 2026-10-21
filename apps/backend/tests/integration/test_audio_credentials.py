"""Real vault and account bindings; only external HTTP/TCP are simulated."""

import base64
from dataclasses import replace
from uuid import uuid4

import httpcore
import httpx
import pytest
from sqlalchemy import text

from agents_factory.modules.audio_ingestion.media import MetaAudioDownloader
from agents_factory.modules.audio_ingestion.source import load_audio_source
from agents_factory.modules.secrets.contracts import SecretAccessDenied
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.repository import SecretVault
from agents_factory.modules.whatsapp.account_service import (
    ACCESS_TOKEN_PURPOSE,
    SessionFactoryMetaAccessTokenResolver,
)
from apps.backend.tests.integration.audio_fixtures import audio_world


async def test_audio_download_uses_real_encrypted_account_credential(
    session_factory, tmp_path
):
    world, message = await audio_world(session_factory)
    context = replace(world[0], actor_id=uuid4(), actor_type="platform_admin")
    key_provider = EnvironmentMasterKeyProvider(
        environment={
            "APP_MASTER_KEY": base64.urlsafe_b64encode(b"\x09" * 32)
            .rstrip(b"=")
            .decode(),
        }
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        reference = await SecretVault.for_session(
            session, key_provider=key_provider
        ).store(
            context=context,
            purpose=ACCESS_TOKEN_PURPOSE,
            record_context=f"whatsapp_account:{world[1]}",
            plaintext=b"synthetic-encrypted-media-credential",
        )
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET access_token_secret_id=:ref WHERE id=:id"
            ),
            {"ref": reference.id, "id": world[1]},
        )
        source = await load_audio_source(session, context, message)
    resolver = SessionFactoryMetaAccessTokenResolver(
        session_factory=session_factory, key_provider=key_provider
    )
    # Anonymous access must remain denied even after the downloader is repaired.
    with pytest.raises(SecretAccessDenied):
        await resolver.resolve(
            context=replace(context, actor_id=None), whatsapp_account_id=world[1]
        )

    def metadata(request):
        assert (
            request.headers["authorization"]
            == "Bearer synthetic-encrypted-media-credential"
        )
        return httpx.Response(
            200,
            json={
                "id": source.media_id,
                "url": "https://lookaside.fbsbx.com/synthetic",
                "mime_type": "audio/ogg",
                "file_size": 3,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(metadata)) as client:
        downloader = MetaAudioDownloader(
            resolver,
            "https://graph.facebook.com/v25.0",
            metadata_client=client,
            network_backend=httpcore.AsyncMockBackend(
                [b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nogg"]
            ),
        )
        result = await downloader.download(
            replace(source, expected_sha256=None), tmp_path / "voice.ogg"
        )
    assert result.size_bytes == 3
    assert (tmp_path / "voice.ogg").read_bytes() == b"ogg"
    async with session_factory.begin() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT actor_id,actor_type FROM public.audit_events WHERE tenant_id=:t "
                        "AND event_type='secret.loaded'"
                    ),
                    {"t": source.tenant_id},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    assert rows[0]["actor_id"] is not None and rows[0]["actor_type"] == "system"
