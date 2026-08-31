from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.media.service import MediaService


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    conversation_days: int = Field(default=90, ge=1, le=3650)
    trace_days: int = Field(default=30, ge=1, le=3650)
    action_months: int = Field(default=12, ge=1, le=120)


TRACE_PROJECTION = """jsonb_strip_nulls(jsonb_build_object(
    'model',runtime_metadata->'model','reasoning_effort',runtime_metadata->'reasoning_effort',
    'agent_spec_digest',runtime_metadata->'agent_spec_digest','usage',runtime_metadata->'usage',
    'conversation_state_version',runtime_metadata->'conversation_state_version'))"""


class RetentionService:
    """Explicit maintenance composition; ordinary app/admin cannot assume this role.

    sessions must belong to a dedicated login allowed to SET agents_factory_retention.
    The database applies its own current cutoffs, independently of job input/clock.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        media: MediaService | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions, self.media = sessions, media
        self.now = now or (lambda: datetime.now(UTC))

    @staticmethod
    async def configure(
        session: AsyncSession,
        *,
        context: TenantContext,
        policy: RetentionPolicy,
        expected_revision: int = 0,
    ) -> int:
        if context.actor_type != "platform_admin" or context.actor_id is None:
            raise ValueError("retention_admin_required")
        await set_tenant_context(session, context.tenant_id)
        # Caller uses the regular admin connection, not the maintenance login.
        row = (
            await session.execute(
                text(
                    "INSERT INTO public.retention_policies(id,tenant_id,conversation_days,trace_days,action_months,revision) "
                    "SELECT :id,:tenant,:conversation_days,:trace_days,:action_months,1 WHERE :expected=0 "
                    "ON CONFLICT (tenant_id) DO UPDATE SET conversation_days=:conversation_days,trace_days=:trace_days,"
                    "action_months=:action_months,revision=retention_policies.revision+1 WHERE retention_policies.revision=:expected RETURNING revision"
                ),
                {
                    "id": new_uuid7(),
                    "tenant": context.tenant_id,
                    **policy.model_dump(),
                    "expected": expected_revision,
                },
            )
        ).scalar_one_or_none()
        if row is None:
            # Existing configurations with nonzero revision use a separate CAS.
            row = await session.scalar(
                text(
                    "UPDATE public.retention_policies SET conversation_days=:conversation_days,trace_days=:trace_days,"
                    "action_months=:action_months,revision=revision+1 WHERE tenant_id=:tenant AND revision=:expected RETURNING revision"
                ),
                {
                    "tenant": context.tenant_id,
                    **policy.model_dump(),
                    "expected": expected_revision,
                },
            )
        if not isinstance(row, int):
            raise ValueError("retention_policy_conflict")
        await AuditService(session).record(
            context=context,
            event_type="retention.configured",
            entity_type="tenant",
            entity_id=context.tenant_id,
            payload={**policy.model_dump(), "revision": row},
        )
        return row

    async def run(self, *, context: TenantContext, limit: int = 100) -> dict[str, int]:
        if (
            context.actor_type != "system"
            or context.actor_id is None
            or not 1 <= limit <= 1000
        ):
            raise ValueError("retention_backend_required")
        counts: dict[str, int] = {}
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_retention"))
            await set_tenant_context(session, context.tenant_id)
            conversation_cutoff = await session.scalar(
                text("SELECT agents_factory_private.retention_cutoff('conversation')")
            )
            params = {"tenant": context.tenant_id, "limit": limit}
            # SKIP LOCKED bounds concurrent cleanup. Preserve IDs and references;
            # only expired content is minimized, not the conversation state graph.
            for label, table, predicate, assignment in (
                (
                    "conversation_content",
                    "messages",
                    "created_at<agents_factory_private.retention_cutoff('conversation') AND content<>'{}'::jsonb",
                    "content='{}'::jsonb",
                ),
                (
                    "detailed_traces",
                    "messages",
                    f"created_at<agents_factory_private.retention_cutoff('trace') AND runtime_metadata IS DISTINCT FROM {TRACE_PROJECTION}",
                    f"runtime_metadata={TRACE_PROJECTION}",
                ),
                (
                    "webhook_content",
                    "whatsapp_webhook_events",
                    "received_at<agents_factory_private.retention_cutoff('conversation') AND (raw_payload<>'{}'::jsonb OR normalized_content<>'{}'::jsonb)",
                    "raw_payload='{}'::jsonb,normalized_content='{}'::jsonb",
                ),
                (
                    "outbound_content",
                    "outbound_messages",
                    "created_at<agents_factory_private.retention_cutoff('conversation') AND payload<>'{}'::jsonb AND status IN ('ACCEPTED','SENT','DELIVERED','READ','FAILED','UNCERTAIN','BLOCKED')",
                    "payload='{}'::jsonb",
                ),
                (
                    "contact_location_content",
                    "media_observations",
                    "EXISTS(SELECT 1 FROM public.messages m WHERE m.tenant_id=media_observations.tenant_id AND m.id=media_observations.id AND m.created_at<agents_factory_private.retention_cutoff('conversation')) AND media_id IS NULL AND observation->>'status'<>'DELETED'",
                    "observation=jsonb_build_object('kind',observation->>'kind','status','DELETED','reason_code','retention_expired')",
                ),
            ):
                result = await session.execute(
                    text(
                        f"WITH due AS (SELECT id FROM public.{table} WHERE tenant_id=:tenant AND ({predicate}) ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED) "
                        f"UPDATE public.{table} SET {assignment} WHERE tenant_id=:tenant AND id IN (SELECT id FROM due) RETURNING id"
                    ),
                    params,
                )
                counts[label] = len(result.all())
            ids = list(
                (
                    await session.scalars(
                        text(
                            "SELECT id FROM public.actions WHERE tenant_id=:tenant AND agents_factory_private.action_retention_due(id) ORDER BY updated_at,id LIMIT :limit FOR UPDATE SKIP LOCKED"
                        ),
                        params,
                    )
                ).all()
            )
            if ids:
                action_params = {"tenant": context.tenant_id, "ids": ids}
                # Foreign-key order; delete children while parent eligibility still exists.
                for table, condition in (
                    ("approval_decisions", "action_id=ANY(:ids)"),
                    (
                        "approval_links",
                        "request_id IN (SELECT id FROM public.approval_requests WHERE tenant_id=:tenant AND action_id=ANY(:ids))",
                    ),
                    ("approval_requests", "action_id=ANY(:ids)"),
                    ("action_events", "action_id=ANY(:ids)"),
                    ("actions", "id=ANY(:ids)"),
                ):
                    counts[table] = len(
                        (
                            await session.execute(
                                text(
                                    f"DELETE FROM public.{table} WHERE tenant_id=:tenant AND {condition} RETURNING id"
                                ),
                                action_params,
                            )
                        ).all()
                    )
            result = await session.execute(
                text(
                    "WITH due AS (SELECT id FROM public.audit_events WHERE tenant_id=:tenant AND occurred_at<agents_factory_private.retention_cutoff('action') ORDER BY occurred_at,id LIMIT :limit) "
                    "DELETE FROM public.audit_events WHERE tenant_id=:tenant AND id IN (SELECT id FROM due) RETURNING id"
                ),
                params,
            )
            counts["audit_records"] = len(result.all())
            if any(counts.values()):
                await AuditService(session).record(
                    context=context,
                    event_type="retention.batch_completed",
                    entity_type="tenant",
                    entity_id=context.tenant_id,
                    payload={"counts": counts},
                )
        if self.media is not None:
            # Physical deletion is separately retryable; MediaService revokes access
            # before removing exact tenant/object paths and retains failed receipts.
            async with self.media._session(context) as session:
                evidence = list(
                    (
                        await session.scalars(
                            text(
                                "SELECT id FROM public.media_evidence WHERE tenant_id=:tenant "
                                "AND (expires_at<=:now OR created_at<:cutoff) "
                                "AND (deleted_at IS NULL OR storage_key IS NOT NULL) ORDER BY created_at,id LIMIT :limit"
                            ),
                            {
                                "tenant": context.tenant_id,
                                "now": self.now(),
                                "cutoff": conversation_cutoff,
                                "limit": limit,
                            },
                        )
                    ).all()
                )
            for identifier in evidence:
                await self.media.delete(context=context, evidence_id=identifier)
            counts["media_objects"] = len(evidence)
        return counts
