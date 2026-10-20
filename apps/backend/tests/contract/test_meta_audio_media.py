from dataclasses import replace
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import uuid4

import httpcore
import httpx
import pytest

from agents_factory.modules.audio_ingestion.models import AudioSource
from agents_factory.modules.audio_ingestion.media import (
    MetaAudioDownloader,
    PinnedMediaBackend,
    AudioDownloadError,
)
from agents_factory.modules.secrets.redaction import ResolvedSecret


def source():
    return AudioSource(
        *(uuid4() for _ in range(5)),
        "wamid.synthetic",
        "123456",
        "audio/ogg; codecs=opus",
        None,
        1,
    )


class WireStream(httpcore.AsyncMockStream):
    def __init__(self, response):
        super().__init__([response])
        self.sni = None

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.sni = server_hostname
        return self


async def test_meta_audio_pins_validated_public_ip_and_tls_host(tmp_path):
    wire = WireStream(
        b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Type: audio/ogg\r\n\r\nogg"
    )
    backend = httpcore.AsyncMockBackend([])
    backend.connect_tcp = AsyncMock(return_value=wire)
    resolve = AsyncMock(return_value=("157.240.1.1",))
    pinned = PinnedMediaBackend(resolve=resolve, backend=backend)
    resolver = AsyncMock()
    resolver.resolve.return_value = ResolvedSecret(b"fixture-token")
    metadata = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "id": "123456",
                    "url": "https://lookaside.fbsbx.com/media?id=1",
                    "mime_type": "audio/ogg",
                    "file_size": 3,
                    "sha256": sha256(b"ogg").hexdigest(),
                },
            )
        )
    )
    async with metadata:
        downloaded = await MetaAudioDownloader(
            resolver,
            "https://graph.facebook.com/v25.0",
            metadata_client=metadata,
            network_backend=pinned,
        ).download(source(), tmp_path / "voice.ogg")
    assert downloaded.size_bytes == 3
    assert (tmp_path / "voice.ogg").read_bytes() == b"ogg"
    assert (tmp_path / "voice.ogg").stat().st_mode & 0o777 == 0o600
    assert backend.connect_tcp.call_args.kwargs["host"] == "157.240.1.1"
    assert wire.sni == "lookaside.fbsbx.com"
    assert resolve.await_count == 1
    assert resolver.resolve.call_args.kwargs["whatsapp_account_id"] is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://lookaside.fbsbx.com/a",
        "https://user:pass@lookaside.fbsbx.com/a",
        "https://lookaside.fbsbx.com:444/a",
        "https://127.0.0.1/a",
        "https://evil.example/a",
        "https://lookaside.fbsbx.com.evil.example/a",
    ],
)
async def test_media_bad_origin_never_receives_token(tmp_path, url):
    resolver = AsyncMock()
    resolver.resolve.return_value = ResolvedSecret(b"fixture-token")
    backend = httpcore.AsyncMockBackend([])
    backend.connect_tcp = AsyncMock()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "id": "123456",
                    "url": url,
                    "file_size": 3,
                    "mime_type": "audio/ogg",
                },
            )
        )
    ) as metadata:
        with pytest.raises(AudioDownloadError):
            await MetaAudioDownloader(
                resolver,
                "https://graph.facebook.com/v25.0",
                metadata_client=metadata,
                network_backend=backend,
            ).download(source(), tmp_path / "voice.ogg")
    backend.connect_tcp.assert_not_called()


@pytest.mark.parametrize(
    "addresses",
    [("127.0.0.1",), ("::1",), ("169.254.169.254",), ("157.240.1.1", "10.0.0.1")],
)
async def test_dns_private_and_mixed_resolution_fail_closed(addresses):
    backend = httpcore.AsyncMockBackend([])
    backend.connect_tcp = AsyncMock()
    pinned = PinnedMediaBackend(
        resolve=AsyncMock(return_value=addresses), backend=backend
    )
    with pytest.raises(AudioDownloadError):
        await pinned.connect_tcp("lookaside.fbsbx.com", 443)
    backend.connect_tcp.assert_not_called()


@pytest.mark.parametrize(
    "response,expected_hash",
    [
        (
            b"HTTP/1.1 302 Found\r\nLocation: https://evil.example\r\nContent-Length: 0\r\n\r\n",
            None,
        ),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 10000001\r\n\r\n", None),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nogg", "0" * 64),
        (b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n" + b"x" * 10000001, None),
    ],
)
async def test_audio_rejects_stream_over_limit_and_hash_mismatch(
    tmp_path, response, expected_hash
):
    wire = WireStream(response)
    backend = httpcore.AsyncMockBackend([])
    backend.connect_tcp = AsyncMock(return_value=wire)
    pinned = PinnedMediaBackend(
        resolve=AsyncMock(return_value=("157.240.1.1",)), backend=backend
    )
    resolver = AsyncMock()
    resolver.resolve.return_value = ResolvedSecret(b"fixture-token")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "id": "123456",
                    "url": "https://lookaside.fbsbx.com/media",
                    "file_size": 3,
                    "mime_type": "audio/ogg",
                },
            )
        )
    ) as metadata:
        with pytest.raises(AudioDownloadError):
            await MetaAudioDownloader(
                resolver,
                "https://graph.facebook.com/v25.0",
                metadata_client=metadata,
                network_backend=pinned,
            ).download(
                replace(source(), expected_sha256=expected_hash), tmp_path / "voice.ogg"
            )
    assert not (tmp_path / "voice.ogg").exists()
