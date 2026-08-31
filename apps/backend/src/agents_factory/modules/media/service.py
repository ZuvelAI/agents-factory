from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.media.contact import normalize_contacts
from agents_factory.modules.media.contracts import (
    MAX_BYTES,
    BinaryMedia,
    MalwareScanner,
    MediaError,
    MediaKind,
    MediaNormalizer,
    NormalizedMediaObservation,
    StoredMedia,
    UnavailableScanner,
)
from agents_factory.modules.media.location import normalize_location
from agents_factory.modules.media.pdf import normalize_pdf
from agents_factory.modules.media.storage import (
    LocalPrivateMediaStore,
    MediaAccessSigner,
)
from agents_factory.modules.media.validation import sniff, matches_provider_digest
from agents_factory.modules.media.video import normalize_video
from agents_factory.modules.whatsapp.contracts import WhatsAppProvider


class MediaService:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        provider: WhatsAppProvider,
        storage: LocalPrivateMediaStore,
        signer: MediaAccessSigner,
        scanner: MalwareScanner | None = None,
        voice: MediaNormalizer | None = None,
        image: MediaNormalizer | None = None,
        retention_days: int = 90,
        language: str = "es",
        vocabulary: tuple[str, ...] = (),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= retention_days <= 365 or language not in {"es", "en"}:
            raise ValueError("invalid media configuration")
        self.sessions, self.provider, self.storage, self.signer = (
            sessions,
            provider,
            storage,
            signer,
        )
        self.scanner = scanner or UnavailableScanner()
        self.voice, self.image = voice, image
        self.retention_days, self.language, self.vocabulary = (
            retention_days,
            language,
            vocabulary,
        )
        self.now = now or (lambda: datetime.now(UTC))

    @asynccontextmanager
    async def _session(
        self, context: TenantContext, *, write: bool = False
    ) -> AsyncIterator[AsyncSession]:
        if (
            context.actor_type not in {"system", "platform_admin"}
            or context.actor_id is None
        ):
            raise MediaError("media_backend_actor_required")
        async with self.sessions.begin() as session:
            await session.execute(
                text(
                    "SET LOCAL ROLE agents_factory_admin"
                    if write
                    else "SET LOCAL ROLE agents_factory_app"
                )
            )
            await set_tenant_context(session, context.tenant_id)
            yield session

    @asynccontextmanager
    async def _lock(
        self, context: TenantContext, media_id: UUID
    ) -> AsyncIterator[None]:
        async with self._session(context) as session:
            key = int.from_bytes(
                hashlib.sha256(
                    f"media:{context.tenant_id}:{media_id}".encode()
                ).digest()[:8],
                "big",
                signed=True,
            )
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": key}
            )
            yield

    async def _get(self, context: TenantContext, media_id: UUID) -> StoredMedia | None:
        async with self._session(context) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM public.media_evidence WHERE tenant_id=:tenant AND id=:id"
                        ),
                        {"tenant": context.tenant_id, "id": media_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            return StoredMedia.model_validate(dict(row)) if row else None

    async def _save(self, context: TenantContext, record: StoredMedia) -> None:
        values = record.model_dump()
        values["observation"] = (
            record.observation.model_dump(mode="json") if record.observation else None
        )
        async with self._session(context, write=True) as session:
            await session.execute(
                text(
                    "INSERT INTO public.media_evidence(id,tenant_id,whatsapp_account_id,provider_media_id,customer_ref,first_message_id,kind,status,content_digest,storage_key,media_type,byte_size,scan_status,observation,created_at,expires_at,deleted_at) VALUES (:id,:tenant_id,:whatsapp_account_id,:provider_media_id,:customer_ref,:first_message_id,:kind,:status,:content_digest,:storage_key,:media_type,:byte_size,:scan_status,:observation,:created_at,:expires_at,:deleted_at) ON CONFLICT(id) DO UPDATE SET status=excluded.status,content_digest=excluded.content_digest,storage_key=excluded.storage_key,media_type=excluded.media_type,byte_size=excluded.byte_size,scan_status=excluded.scan_status,observation=excluded.observation,deleted_at=excluded.deleted_at"
                ).bindparams(bindparam("observation", type_=JSONB(none_as_null=True))),
                values,
            )

    async def _attach(
        self,
        context: TenantContext,
        message_id: UUID,
        observation: NormalizedMediaObservation,
    ) -> None:
        async with self._session(context, write=True) as session:
            await session.execute(
                text(
                    "INSERT INTO public.media_observations(id,tenant_id,media_id,observation) VALUES (:id,:tenant,:media_id,:observation) ON CONFLICT(id) DO UPDATE SET media_id=excluded.media_id,observation=excluded.observation"
                ).bindparams(bindparam("observation", type_=JSONB)),
                {
                    "tenant": context.tenant_id,
                    "id": message_id,
                    "observation": observation.model_dump(mode="json"),
                    "media_id": observation.evidence_id,
                },
            )

    async def process(
        self, *, context: TenantContext, message_id: UUID, retry_pending: bool = False
    ) -> NormalizedMediaObservation:
        async with self._session(context) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT m.content,m.message_type,c.customer_wa_id,c.whatsapp_account_id,a.phone_number_id FROM public.messages m JOIN public.conversations c ON c.tenant_id=m.tenant_id AND c.id=m.conversation_id JOIN public.whatsapp_accounts a ON a.tenant_id=c.tenant_id AND a.id=c.whatsapp_account_id WHERE m.tenant_id=:tenant AND m.id=:id AND m.direction='inbound' AND m.sender_type='customer'"
                        ),
                        {"tenant": context.tenant_id, "id": message_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise MediaError("media_message_unavailable")
        kind = cast(MediaKind, row["message_type"])
        content = dict(row["content"])
        if kind in {"text", "location", "contacts"}:
            try:
                raw = {k: v for k, v in content.items() if k != "media_observation"}
                observation = (
                    normalize_location(raw)
                    if kind == "location"
                    else normalize_contacts(raw)
                    if kind == "contacts"
                    else NormalizedMediaObservation(
                        kind="text", status="READY", text=raw["text"]
                    )
                )
            except (ValueError, KeyError):
                observation = NormalizedMediaObservation(
                    kind=kind, status="FAILED", reason_code="media_payload_invalid"
                )
            await self._attach(context, message_id, observation)
            return observation
        provider_id = content.get("id")
        if (
            kind not in {"audio", "image", "document", "video"}
            or not isinstance(provider_id, str)
            or not provider_id.isascii()
            or not provider_id.isdigit()
            or len(provider_id) > 200
        ):
            observation = NormalizedMediaObservation(
                kind=kind, status="FAILED", reason_code="media_reference_invalid"
            )
            await self._attach(context, message_id, observation)
            return observation
        media_id = uuid5(row["whatsapp_account_id"], provider_id)
        async with self._lock(context, media_id):
            record = await self._get(context, media_id)
            if record:
                if record.customer_ref != row["customer_wa_id"] or record.kind != kind:
                    raise MediaError("media_access_denied")
                if record.deleted_at or record.expires_at <= self.now():
                    observation = NormalizedMediaObservation(
                        kind=kind,
                        status="DELETED",
                        reason_code="media_expired_or_deleted",
                    )
                    await self._attach(context, message_id, observation)
                    return observation
                if record.status == "PROCESSING":
                    observation = NormalizedMediaObservation(
                        kind=kind,
                        status="HUMAN_REVIEW",
                        evidence_id=media_id,
                        expires_at=record.expires_at,
                        reason_code="media_processing_interrupted",
                    )
                    record = record.model_copy(
                        update={
                            "status": observation.status,
                            "observation": observation,
                        }
                    )
                    await self._save(context, record)
                if not (
                    retry_pending
                    and record.status in {"PENDING_PROVIDER", "QUARANTINED"}
                    and record.scan_status != "INFECTED"
                ):
                    assert record.observation is not None
                    await self._attach(context, message_id, record.observation)
                    return record.observation
            else:
                created = self.now()
                record = StoredMedia(
                    id=media_id,
                    tenant_id=context.tenant_id,
                    whatsapp_account_id=row["whatsapp_account_id"],
                    provider_media_id=provider_id,
                    customer_ref=row["customer_wa_id"],
                    first_message_id=message_id,
                    kind=kind,
                    status="PROCESSING",
                    created_at=created,
                    expires_at=created + timedelta(days=self.retention_days),
                )
            record = record.model_copy(update={"status": "PROCESSING"})
            await self._save(context, record)
            try:
                if record.content_digest:
                    binary = await self.storage.read(
                        tenant_id=context.tenant_id,
                        media_id=media_id,
                        digest=record.content_digest,
                    )
                    media_type = record.media_type or ""
                else:
                    binary, media_type = await self.provider.download_media(
                        context=context,
                        whatsapp_account_id=row["whatsapp_account_id"],
                        phone_number_id=row["phone_number_id"],
                        media_id=provider_id,
                        max_bytes=MAX_BYTES,
                    )
                    key, digest = await self.storage.put(
                        tenant_id=context.tenant_id, media_id=media_id, content=binary
                    )
                    record = record.model_copy(
                        update={
                            "content_digest": digest,
                            "storage_key": key,
                            "media_type": media_type,
                            "byte_size": len(binary),
                        }
                    )
                    # Persist the original before scanner/parser/provider work.
                    await self._save(context, record)
                claimed_digest = content.get("sha256")
                if claimed_digest is not None and not matches_provider_digest(
                    binary, claimed_digest
                ):
                    raise MediaError("media_integrity_failed")
                media_type = sniff(binary, claimed=media_type, kind=kind)
                if isinstance(content.get("mime_type"), str):
                    sniff(binary, claimed=content["mime_type"], kind=kind)
                try:
                    scan = await self.scanner.scan(binary, media_type=media_type)
                except Exception:
                    scan = "UNAVAILABLE"
                if scan not in {"CLEAN", "INFECTED", "UNAVAILABLE"}:
                    scan = "UNAVAILABLE"
                record = record.model_copy(update={"scan_status": scan})
                await self._save(context, record)
                if scan != "CLEAN":
                    observation = NormalizedMediaObservation(
                        kind=kind,
                        status="QUARANTINED",
                        reason_code="media_scan_" + scan.lower(),
                    )
                elif kind == "video":
                    observation = normalize_video(
                        media_type=media_type, byte_size=len(binary)
                    )
                elif kind == "document":
                    observation = await normalize_pdf(binary)
                else:
                    normalizer = self.voice if kind == "audio" else self.image
                    observation = (
                        await normalizer.normalize(
                            binary,
                            media_type=media_type,
                            language=self.language,
                            vocabulary=self.vocabulary,
                        )
                        if normalizer
                        else NormalizedMediaObservation(
                            kind=kind,
                            status="PENDING_PROVIDER",
                            reason_code="media_analysis_not_configured",
                        )
                    )
                    if observation.kind != kind:
                        raise MediaError("media_observation_invalid")
            except MediaError as error:
                observation = NormalizedMediaObservation(
                    kind=kind, status="FAILED", reason_code=str(error)
                )
            except Exception:
                observation = NormalizedMediaObservation(
                    kind=kind, status="FAILED", reason_code="media_processing_failed"
                )
            observation = observation.model_copy(
                update={"evidence_id": media_id, "expires_at": record.expires_at}
            )
            record = record.model_copy(
                update={"status": observation.status, "observation": observation}
            )
            await self._save(context, record)
            await self._attach(context, message_id, observation)
            async with self._session(context, write=True) as session:
                await AuditService(session).record(
                    context=context,
                    event_type="media.normalized",
                    entity_type="media",
                    entity_id=media_id,
                    payload={
                        "kind": kind,
                        "status": observation.status,
                        "usage": observation.usage.model_dump(mode="json"),
                    },
                )
            return observation

    async def allowed(
        self, *, context: TenantContext, customer_ref: str, evidence_id: UUID
    ) -> bool:
        record = await self._get(context, evidence_id)
        return bool(
            record
            and record.customer_ref == customer_ref
            and record.content_digest
            and record.scan_status == "CLEAN"
            and record.status in {"READY", "PENDING_PROVIDER", "HUMAN_REVIEW"}
            and not record.deleted_at
            and record.expires_at > self.now()
        )

    async def export_evidence(
        self, *, context: TenantContext, customer_ref: str, evidence_id: UUID
    ) -> BinaryMedia:
        """Backend-only scoped original for an authorized evidence destination.

        No URL, public object, identity assertion or model annotation is exported.
        The caller must retain the destination receipt for downstream deletion.
        """
        async with self._lock(context, evidence_id):
            if not await self.allowed(
                context=context, customer_ref=customer_ref, evidence_id=evidence_id
            ):
                raise MediaError("media_access_denied")
            record = await self._get(context, evidence_id)
            if record is None or not record.content_digest or not record.media_type:
                raise MediaError("media_unavailable")
            return BinaryMedia(
                content=await self.storage.read(
                    tenant_id=context.tenant_id,
                    media_id=evidence_id,
                    digest=record.content_digest,
                ),
                media_type=record.media_type,
            )

    async def signed_access(
        self,
        *,
        context: TenantContext,
        customer_ref: str,
        evidence_id: UUID,
        lifetime_seconds: int = 60,
    ) -> str:
        if not 1 <= lifetime_seconds <= 300 or not await self.allowed(
            context=context, customer_ref=customer_ref, evidence_id=evidence_id
        ):
            raise MediaError("media_access_denied")
        expires = int(self.now().timestamp()) + lifetime_seconds
        signature = self.signer.sign(
            tenant_id=context.tenant_id,
            customer_ref=customer_ref,
            media_id=evidence_id,
            expires=expires,
        )
        return f"/admin/tenants/{context.tenant_id}/media/{evidence_id}/download?expires={expires}&signature={signature}"

    async def read_signed(
        self,
        *,
        context: TenantContext,
        customer_ref: str,
        evidence_id: UUID,
        expires: int,
        signature: str,
    ) -> bytes:
        async with self._lock(context, evidence_id):
            self.signer.verify(
                tenant_id=context.tenant_id,
                customer_ref=customer_ref,
                media_id=evidence_id,
                expires=expires,
                signature=signature,
                now=int(self.now().timestamp()),
            )
            if not await self.allowed(
                context=context, customer_ref=customer_ref, evidence_id=evidence_id
            ):
                raise MediaError("media_access_denied")
            record = await self._get(context, evidence_id)
            assert record and record.content_digest
            return await self.storage.read(
                tenant_id=context.tenant_id,
                media_id=evidence_id,
                digest=record.content_digest,
            )

    async def delete(self, *, context: TenantContext, evidence_id: UUID) -> None:
        async with self._lock(context, evidence_id):
            record = await self._get(context, evidence_id)
            if record is None:
                raise MediaError("media_unavailable")
            # Revoke first; an interrupted physical delete remains safely retryable.
            record = record.model_copy(
                update={
                    "status": "DELETED",
                    "deleted_at": record.deleted_at or self.now(),
                    "observation": None,
                    "storage_key": record.storage_key
                    or f"{context.tenant_id}/{evidence_id}",
                }
            )
            await self._save(context, record)
            async with self._session(context, write=True) as session:
                await session.execute(
                    text(
                        "UPDATE public.media_observations SET observation=:observation WHERE tenant_id=:tenant AND media_id=:id"
                    ).bindparams(bindparam("observation", type_=JSONB)),
                    {
                        "tenant": context.tenant_id,
                        "id": evidence_id,
                        "observation": NormalizedMediaObservation(
                            kind=record.kind,
                            status="DELETED",
                            reason_code="media_deleted",
                        ).model_dump(mode="json"),
                    },
                )
            await self.storage.delete_object(
                tenant_id=context.tenant_id, media_id=evidence_id
            )
            record = record.model_copy(
                update={"content_digest": None, "storage_key": None, "byte_size": 0}
            )
            await self._save(context, record)
            async with self._session(context, write=True) as session:
                await AuditService(session).record(
                    context=context,
                    event_type="media.deleted",
                    entity_type="media",
                    entity_id=evidence_id,
                    payload={"kind": record.kind},
                )

    async def purge_expired(self, *, context: TenantContext, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("invalid purge limit")
        async with self._session(context) as session:
            identifiers = (
                (
                    await session.execute(
                        text(
                            "SELECT id FROM public.media_evidence WHERE tenant_id=:tenant AND expires_at<=:now AND (deleted_at IS NULL OR storage_key IS NOT NULL) ORDER BY expires_at LIMIT :limit"
                        ),
                        {
                            "tenant": context.tenant_id,
                            "now": self.now(),
                            "limit": limit,
                        },
                    )
                )
                .scalars()
                .all()
            )
        for identifier in identifiers:
            await self.delete(context=context, evidence_id=identifier)
        return len(identifiers)


def observation_text(content: dict[str, object]) -> str | None:
    raw = content.get("media_observation")
    if raw is None:
        return None
    try:
        observation = NormalizedMediaObservation.model_validate(raw)
    except ValidationError:
        return None
    if observation.expires_at is not None and observation.expires_at <= datetime.now(
        UTC
    ):
        return "[Media expired; content unavailable]"
    payload = {
        "kind": observation.kind,
        "status": observation.status,
        "text": observation.text,
        "fields": observation.fields,
        "reason_code": observation.reason_code,
    }
    return (
        "[Untrusted customer media; not identity or authorization evidence]\n"
        + json.dumps(payload, ensure_ascii=False, allow_nan=False)
    )
