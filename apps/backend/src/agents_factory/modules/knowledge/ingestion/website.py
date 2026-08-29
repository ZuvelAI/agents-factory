from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from agents_factory.modules.knowledge.ingestion.contracts import (
    ExtractedBlock,
    ExtractedDocument,
    FetchedSource,
    IngestionRejected,
    MAX_SOURCE_BYTES,
    SourceDescriptor,
)


AddressResolver = Callable[[str], Awaitable[tuple[str, ...]]]


async def resolve_public_addresses(hostname: str) -> tuple[str, ...]:
    records = await asyncio.to_thread(
        socket.getaddrinfo,
        hostname,
        443,
        socket.AF_UNSPEC,
        socket.SOCK_STREAM,
    )
    addresses = tuple(sorted({str(record[4][0]) for record in records}))
    if not addresses:
        raise IngestionRejected("website_dns_unresolved")
    return addresses


class WebsiteFetcher:
    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        client: httpx.AsyncClient | None = None,
        resolver: AddressResolver = resolve_public_addresses,
        max_bytes: int = MAX_SOURCE_BYTES,
    ) -> None:
        self._allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        self._client = client
        self._resolver = resolver
        self._max_bytes = max_bytes

    async def fetch(self, source: SourceDescriptor) -> FetchedSource:
        url = source.configuration.get("url")
        if not isinstance(url, str):
            raise IngestionRejected("website_url_required")
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if (
            parsed.scheme != "https"
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or hostname.lower() not in self._allowed_hosts
        ):
            raise IngestionRejected("website_url_not_allowed")
        await self._assert_public(hostname)

        if self._client is None:
            async with httpx.AsyncClient(
                timeout=20.0, follow_redirects=False
            ) as client:
                response = await client.get(url)
        else:
            response = await self._client.get(url)
        if response.is_redirect:
            raise IngestionRejected("website_redirect_rejected")
        if response.status_code != 200:
            raise IngestionRejected("website_fetch_failed")
        media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type not in {"text/html", "application/xhtml+xml"}:
            raise IngestionRejected("website_content_type_unsupported")
        if len(response.content) > self._max_bytes:
            raise IngestionRejected("source_too_large")
        return FetchedSource(
            descriptor=source,
            content=response.content,
            media_type=media_type,
            filename="index.html",
            locator={"url": url},
            content_digest=hashlib.sha256(response.content).hexdigest(),
        )

    async def _assert_public(self, hostname: str) -> None:
        addresses: tuple[str, ...]
        try:
            direct = ipaddress.ip_address(hostname)
            addresses = (str(direct),)
        except ValueError:
            addresses = await self._resolver(hostname)
        for value in addresses:
            address = ipaddress.ip_address(value)
            if not address.is_global:
                raise IngestionRejected("website_private_network_rejected")


class WebsiteExtractor:
    def extract(self, fetched: FetchedSource) -> ExtractedDocument:
        try:
            html = fetched.content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise IngestionRejected("website_encoding_unsupported") from None
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript", "template"]):
            element.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else fetched.filename
        text = "\n".join(
            line
            for line in (value.strip() for value in soup.get_text("\n").splitlines())
            if line
        )
        if not text:
            raise IngestionRejected("source_has_no_extractable_text")
        return ExtractedDocument(
            title=title[:300],
            blocks=(ExtractedBlock(kind="TEXT", text=text, locator=fetched.locator),),
            source_digest=fetched.content_digest,
        )
