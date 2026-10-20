"""Account-scoped media download with a pinned public TCP destination."""

import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
import socket
from typing import AsyncIterator, Awaitable, Callable, Iterable
from urllib.parse import urlsplit

import httpcore
import httpx

from agents_factory.common.context import TenantContext
from agents_factory.modules.whatsapp.contracts import MetaAccessTokenResolver
from .models import AudioSource

MEDIA_HOST = "lookaside.fbsbx.com"
MAX_BYTES = 10_000_000


class AudioDownloadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AudioDownload:
    size_bytes: int
    sha256: str
    mime_type: str


async def _resolve(host: str) -> tuple[str, ...]:
    records = await asyncio.get_running_loop().getaddrinfo(
        host, 443, type=socket.SOCK_STREAM
    )
    return tuple(str(record[4][0]) for record in records)


class PinnedMediaBackend(httpcore.AsyncNetworkBackend):
    """httpcore keeps the original origin for Host and certificate/SNI checks."""

    def __init__(
        self,
        *,
        resolve: Callable[[str], Awaitable[tuple[str, ...]]] = _resolve,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self.resolve = resolve
        self.backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if host != MEDIA_HOST or port != 443:
            raise AudioDownloadError("audio_media_origin_invalid")
        addresses = await self.resolve(host)
        parsed_addresses = tuple(ipaddress.ip_address(address) for address in addresses)
        if not parsed_addresses or any(
            not address.is_global or address.is_multicast or address.is_reserved
            for address in parsed_addresses
        ):
            raise AudioDownloadError("audio_media_address_invalid")
        # The lower backend sees only an already-validated numeric address.
        # There is no second hostname resolution between validation and connect.
        return await self.backend.connect_tcp(
            host=addresses[0],
            port=443,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


def _origin(url: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname == MEDIA_HOST
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise AudioDownloadError("audio_media_origin_invalid")


def _digest(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AudioDownloadError("audio_media_hash_invalid")
    if len(value) == 64:
        try:
            return bytes.fromhex(value).hex()
        except ValueError:
            pass
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) == 32:
            return raw.hex()
    except ValueError:
        pass
    raise AudioDownloadError("audio_media_hash_invalid")


def _mime(value: object) -> str:
    if (
        not isinstance(value, str)
        or value.split(";", 1)[0].strip().lower() != "audio/ogg"
    ):
        raise AudioDownloadError("audio_format_unsupported")
    return value


class MetaAudioDownloader:
    def __init__(
        self,
        access_tokens: MetaAccessTokenResolver,
        graph_api_base_url: str,
        *,
        metadata_client: httpx.AsyncClient | None = None,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        graph = urlsplit(graph_api_base_url)
        if (
            graph.scheme != "https"
            or graph.hostname != "graph.facebook.com"
            or graph.port not in {None, 443}
            or graph.username
            or graph.password
            or graph.query
            or graph.fragment
        ):
            raise ValueError("audio_graph_origin_invalid")
        self.access_tokens = access_tokens
        self.graph_api_base_url = graph_api_base_url.rstrip("/")
        self.metadata_client = metadata_client
        self.network_backend = network_backend or PinnedMediaBackend()

    @asynccontextmanager
    async def _metadata(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.metadata_client is not None:
            yield self.metadata_client
        else:
            async with httpx.AsyncClient(
                timeout=15.0, follow_redirects=False, trust_env=False
            ) as client:
                yield client

    async def download(self, source: AudioSource, destination: Path) -> AudioDownload:
        created = False
        try:
            if (
                not source.media_id.isascii()
                or not source.media_id.isdigit()
                or len(source.media_id) > 200
            ):
                raise AudioDownloadError("audio_media_id_invalid")
            _mime(source.mime_type)
            context = TenantContext(source.tenant_id, None, "system", source.event_id)
            resolved_access = await self.access_tokens.resolve(
                context=context, whatsapp_account_id=source.account_id
            )
            headers = {
                "Authorization": "Bearer "
                + resolved_access.reveal().decode("utf-8", errors="strict")
            }
            async with asyncio.timeout(15):
                async with self._metadata() as client:
                    async with client.stream(
                        "GET",
                        f"{self.graph_api_base_url}/{source.media_id}",
                        headers=headers,
                        follow_redirects=False,
                        timeout=15.0,
                    ) as response:
                        if response.status_code != 200:
                            raise AudioDownloadError("audio_metadata_rejected")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 65536:
                                raise AudioDownloadError("audio_metadata_invalid")
                        metadata = json.loads(body)
            if not isinstance(metadata, dict) or metadata.get("id") != source.media_id:
                raise AudioDownloadError("audio_metadata_identity_invalid")
            url = metadata.get("url")
            if not isinstance(url, str):
                raise AudioDownloadError("audio_metadata_invalid")
            _origin(url)
            mime = _mime(metadata.get("mime_type"))
            size = metadata.get("file_size")
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or not 0 < size <= MAX_BYTES
            ):
                raise AudioDownloadError("audio_size_invalid")
            expected_hashes = [
                value
                for value in (source.expected_sha256, _digest(metadata.get("sha256")))
                if value is not None
            ]
            digest = sha256()
            count = 0
            async with asyncio.timeout(15):
                async with httpcore.AsyncConnectionPool(
                    network_backend=self.network_backend,
                    retries=0,
                    max_connections=1,
                    max_keepalive_connections=0,
                ) as pool:
                    async with pool.stream(
                        "GET",
                        url,
                        headers=list(headers.items()),
                        extensions={
                            "timeout": {
                                "connect": 15,
                                "read": 15,
                                "write": 15,
                                "pool": 15,
                            }
                        },
                    ) as response:
                        if response.status != 200:
                            raise AudioDownloadError("audio_download_rejected")
                        response_headers = {
                            key.lower(): value for key, value in response.headers
                        }
                        length = response_headers.get(b"content-length")
                        if length is not None and (
                            not length.isdigit() or not 0 < int(length) <= MAX_BYTES
                        ):
                            raise AudioDownloadError("audio_size_invalid")
                        encoding = response_headers.get(b"content-encoding")
                        if encoding not in {None, b"identity"}:
                            raise AudioDownloadError("audio_media_encoding_invalid")
                        fd = os.open(
                            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                        )
                        created = True
                        with os.fdopen(fd, "wb") as target:
                            async for chunk in response.aiter_stream():
                                count += len(chunk)
                                if count > MAX_BYTES:
                                    raise AudioDownloadError("audio_size_invalid")
                                digest.update(chunk)
                                target.write(chunk)
            if count != size or any(
                value != digest.hexdigest() for value in expected_hashes
            ):
                raise AudioDownloadError("audio_media_integrity_invalid")
            return AudioDownload(count, digest.hexdigest(), mime)
        except BaseException as exc:
            if created:
                destination.unlink(missing_ok=True)
            if isinstance(exc, (AudioDownloadError, asyncio.CancelledError)):
                raise
            raise AudioDownloadError("audio_download_failed") from None
