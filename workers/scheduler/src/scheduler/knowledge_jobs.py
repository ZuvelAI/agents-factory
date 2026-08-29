from __future__ import annotations

from typing import Any, cast
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.queue import JobEnvelope, JobHandler
from agents_factory.database import Database, set_tenant_context


class InvalidKnowledgeChangeJob(ValueError):
    pass


async def configure_knowledge_jobs(
    context: dict[Any, Any], *, database: Database
) -> None:
    async def detect_change_handler(envelope: JobEnvelope) -> None:
        await detect_source_change(envelope=envelope, database=database)

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers["knowledge.detect_change"] = detect_change_handler


async def detect_source_change(*, envelope: JobEnvelope, database: Database) -> None:
    if envelope.kind != "knowledge.detect_change":
        raise InvalidKnowledgeChangeJob("unexpected job kind")

    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        ingestion = (
            (
                await session.execute(
                    text(
                        "SELECT source_id, content_digest, proposed_artifact_count "
                        "FROM public.knowledge_ingestions WHERE tenant_id = :tenant_id "
                        "AND id = :ingestion_id AND state = 'SUCCEEDED'"
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
        if ingestion is None or ingestion["content_digest"] is None:
            raise InvalidKnowledgeChangeJob("completed ingestion is required")
        source_id = ingestion["source_id"]
        content_digest = ingestion["content_digest"]
        artifact_count = ingestion["proposed_artifact_count"]
        diff_id = await session.scalar(
            text(
                "SELECT agents_factory_private.record_knowledge_source_diff("
                ":id, :tenant_id, :source_id, :ingestion_id, :digest, :summary)"
            ).bindparams(bindparam("summary", type_=JSONB)),
            {
                "id": new_uuid7(),
                "tenant_id": envelope.tenant_id,
                "source_id": source_id,
                "ingestion_id": envelope.aggregate_id,
                "digest": content_digest,
                "summary": {"proposed_artifact_count": artifact_count},
            },
        )
        await AuditService(session).record(
            context=TenantContext(
                tenant_id=envelope.tenant_id,
                actor_id=None,
                actor_type="system",
                correlation_id=envelope.job_id,
            ),
            event_type=(
                "knowledge.source_change.detected"
                if diff_id is not None
                else "knowledge.source_change.unchanged"
            ),
            entity_type="knowledge_ingestion",
            entity_id=envelope.aggregate_id,
            payload={
                "source_id": str(source_id),
                "diff_id": None if diff_id is None else str(diff_id),
                "content_digest": content_digest,
            },
        )
