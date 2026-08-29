from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.common.queue import (
    JobEnvelope,
    JobHandler,
    configure_durable_worker,
)
from agents_factory.database import Database, set_tenant_context
from agents_factory.modules.knowledge.ingestion.contracts import (
    DocumentExtractor,
    DriveFileClient,
    FetchedSource,
    IngestionRejected,
    NormalizedKnowledge,
    SourceDescriptor,
)
from agents_factory.modules.knowledge.ingestion.docx import DocxExtractor
from agents_factory.modules.knowledge.ingestion.drive import GoogleDriveFetcher
from agents_factory.modules.knowledge.ingestion.manual import (
    ManualExtractor,
    ManualFetcher,
)
from agents_factory.modules.knowledge.ingestion.normalizer import KnowledgeNormalizer
from agents_factory.modules.knowledge.ingestion.pdf import PdfExtractor
from agents_factory.modules.knowledge.ingestion.spreadsheet import SpreadsheetExtractor
from agents_factory.modules.knowledge.ingestion.storage import LocalPrivateSourceStore
from agents_factory.modules.knowledge.ingestion.uploads import UploadedFileFetcher
from agents_factory.modules.knowledge.ingestion.website import (
    WebsiteExtractor,
    WebsiteFetcher,
)
from knowledge_worker.embedding_jobs import configure_embedding_jobs


class InvalidKnowledgeIngestionJob(ValueError):
    pass


async def configure_knowledge_worker(context: dict[Any, Any]) -> None:
    await configure_durable_worker(context)
    database = cast(Database, context["database"])
    store = cast(
        LocalPrivateSourceStore,
        context.get("knowledge_source_store")
        or LocalPrivateSourceStore(
            Path(
                os.environ.get(
                    "KNOWLEDGE_STORAGE_ROOT",
                    "/var/lib/agents-factory/knowledge",
                )
            )
        ),
    )
    drive_client = cast(DriveFileClient | None, context.get("drive_file_client"))

    async def ingest_handler(envelope: JobEnvelope) -> None:
        await handle_ingestion(
            envelope=envelope,
            database=database,
            store=store,
            drive_client=drive_client,
        )

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers["knowledge.ingest"] = ingest_handler
    await configure_embedding_jobs(context, database=database)


async def handle_ingestion(
    *,
    envelope: JobEnvelope,
    database: Database,
    store: LocalPrivateSourceStore,
    drive_client: DriveFileClient | None,
) -> None:
    if envelope.kind != "knowledge.ingest":
        raise InvalidKnowledgeIngestionJob("unexpected job kind")
    source = await _claim(database=database, envelope=envelope)
    if source is None:
        return
    try:
        fetched = await _fetch(source=source, store=store, drive_client=drive_client)
        storage_path = await store.put(
            tenant_id=source.tenant_id,
            source_id=source.source_id,
            digest=fetched.content_digest,
            content=fetched.content,
            media_type=fetched.media_type,
        )
        extracted = _extractor(fetched).extract(fetched)
        normalized = KnowledgeNormalizer().normalize(
            source=source,
            document=extracted,
        )
        await _complete(
            database=database,
            envelope=envelope,
            source=source,
            storage_path=storage_path,
            fetched=fetched,
            normalized=normalized,
        )
    except IngestionRejected as error:
        await _fail(database=database, envelope=envelope, error_code=error.code)


async def _claim(
    *, database: Database, envelope: JobEnvelope
) -> SourceDescriptor | None:
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        state = await session.scalar(
            text(
                "UPDATE public.knowledge_ingestions SET state = 'PROCESSING', "
                "updated_at = now() WHERE tenant_id = :tenant_id AND id = :ingestion_id "
                "AND state = 'PENDING' RETURNING state"
            ),
            {
                "tenant_id": envelope.tenant_id,
                "ingestion_id": envelope.aggregate_id,
            },
        )
        if state is None:
            state = await session.scalar(
                text(
                    "SELECT state FROM public.knowledge_ingestions "
                    "WHERE tenant_id = :tenant_id AND id = :ingestion_id"
                ),
                {
                    "tenant_id": envelope.tenant_id,
                    "ingestion_id": envelope.aggregate_id,
                },
            )
        if state != "PROCESSING":
            return None
        row = (
            (
                await session.execute(
                    text(
                        "SELECT source.id AS source_id, source.source_type, "
                        "source.authority, source.configuration "
                        "FROM public.knowledge_ingestions AS ingestion "
                        "JOIN public.knowledge_sources AS source "
                        "ON source.tenant_id = ingestion.tenant_id "
                        "AND source.id = ingestion.source_id "
                        "WHERE ingestion.tenant_id = :tenant_id "
                        "AND ingestion.id = :ingestion_id"
                    ),
                    {
                        "tenant_id": envelope.tenant_id,
                        "ingestion_id": envelope.aggregate_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise InvalidKnowledgeIngestionJob("ingestion source is unavailable")
        return SourceDescriptor(
            tenant_id=envelope.tenant_id,
            source_id=row["source_id"],
            source_type=row["source_type"],
            authority=row["authority"],
            configuration=row["configuration"],
        )


async def _fetch(
    *,
    source: SourceDescriptor,
    store: LocalPrivateSourceStore,
    drive_client: DriveFileClient | None,
) -> FetchedSource:
    if source.source_type == "WEBSITE":
        url = source.configuration.get("url")
        host = urlsplit(url).hostname if isinstance(url, str) else None
        if host is None:
            raise IngestionRejected("website_url_required")
        return await WebsiteFetcher(allowed_hosts=frozenset({host})).fetch(source)
    if source.source_type == "MANUAL":
        return await ManualFetcher().fetch(source)
    if source.source_type == "GOOGLE_DRIVE":
        if drive_client is None:
            raise IngestionRejected("drive_client_unavailable")
        return await GoogleDriveFetcher(drive_client).fetch(source)
    return await UploadedFileFetcher(store).fetch(source)


def _extractor(fetched: FetchedSource) -> DocumentExtractor:
    source_type = fetched.descriptor.source_type
    media_type = fetched.media_type.lower()
    if source_type == "WEBSITE":
        return WebsiteExtractor()
    if source_type == "MANUAL" or media_type == "text/plain":
        return ManualExtractor()
    if source_type == "PDF" or media_type == "application/pdf":
        return PdfExtractor()
    if source_type == "DOCX" or "wordprocessingml" in media_type:
        return DocxExtractor()
    if source_type == "SPREADSHEET" or "spreadsheetml" in media_type:
        return SpreadsheetExtractor()
    if media_type == "application/json":
        return SpreadsheetExtractor()
    raise IngestionRejected("source_type_unsupported")


async def _complete(
    *,
    database: Database,
    envelope: JobEnvelope,
    source: SourceDescriptor,
    storage_path: str,
    fetched: FetchedSource,
    normalized: NormalizedKnowledge,
) -> None:
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        inserted = 0
        artifact_rows = tuple(("FACT", item) for item in normalized.facts) + tuple(
            ("DOCUMENT", item) for item in normalized.documents
        )
        statement = text(
            "SELECT agents_factory_private.append_knowledge_ingestion_artifact("
            ":id, :tenant_id, :source_id, :ingestion_id, :artifact_type, "
            ":artifact_digest, :proposal)"
        ).bindparams(bindparam("proposal", type_=JSONB))
        for artifact_type, artifact in artifact_rows:
            requested_id = new_uuid7()
            result = await session.execute(
                statement,
                {
                    "id": requested_id,
                    "tenant_id": source.tenant_id,
                    "source_id": source.source_id,
                    "ingestion_id": envelope.aggregate_id,
                    "artifact_type": artifact_type,
                    "artifact_digest": artifact.content_digest,
                    "proposal": artifact.model_dump(mode="json"),
                },
            )
            artifact_id = result.scalar_one()
            if artifact_id == requested_id:
                inserted += 1
        updated = await session.scalar(
            text(
                "UPDATE public.knowledge_ingestions SET state = 'SUCCEEDED', "
                "content_digest = :content_digest, storage_path = :storage_path, "
                "proposed_artifact_count = :artifact_count, error_code = NULL, "
                "completed_at = now(), updated_at = now() "
                "WHERE tenant_id = :tenant_id AND id = :ingestion_id "
                "AND state = 'PROCESSING' RETURNING id"
            ),
            {
                "content_digest": fetched.content_digest,
                "storage_path": storage_path,
                "artifact_count": inserted,
                "tenant_id": source.tenant_id,
                "ingestion_id": envelope.aggregate_id,
            },
        )
        if updated != envelope.aggregate_id:
            raise InvalidKnowledgeIngestionJob("ingestion completion state changed")
        await OutboxService(session).enqueue(
            context=_context(envelope),
            idempotency_key=f"knowledge.detect_change:{envelope.aggregate_id}",
            topic="knowledge.detect_change",
            payload={
                "aggregate_id": str(envelope.aggregate_id),
                "source_id": str(source.source_id),
                "content_digest": fetched.content_digest,
                "artifact_count": inserted,
            },
        )
        await AuditService(session).record(
            context=_context(envelope),
            event_type="knowledge.ingestion.succeeded",
            entity_type="knowledge_ingestion",
            entity_id=envelope.aggregate_id,
            payload={
                "source_id": str(source.source_id),
                "source_digest": fetched.content_digest,
                "proposed_artifact_count": inserted,
            },
        )


async def _fail(*, database: Database, envelope: JobEnvelope, error_code: str) -> None:
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        updated = await session.scalar(
            text(
                "UPDATE public.knowledge_ingestions SET state = 'FAILED', "
                "error_code = :error_code, completed_at = now(), updated_at = now() "
                "WHERE tenant_id = :tenant_id AND id = :ingestion_id "
                "AND state = 'PROCESSING' RETURNING id"
            ),
            {
                "error_code": error_code,
                "tenant_id": envelope.tenant_id,
                "ingestion_id": envelope.aggregate_id,
            },
        )
        if updated is None:
            return
        await AuditService(session).record(
            context=_context(envelope),
            event_type="knowledge.ingestion.failed",
            entity_type="knowledge_ingestion",
            entity_id=envelope.aggregate_id,
            payload={"error_code": error_code},
        )


def _context(envelope: JobEnvelope) -> TenantContext:
    return TenantContext(
        tenant_id=envelope.tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=envelope.job_id,
    )
