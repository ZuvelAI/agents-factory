from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.database import set_tenant_context
from agents_factory.modules.privacy.export import build_export_manifest
from agents_factory.modules.privacy.minimization import pseudonymize


class PrivacyProcessor:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def process(self, *, tenant_id: UUID, job_id: UUID) -> None:
        async with self._sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_retention"))
            await set_tenant_context(session, tenant_id)
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT operation,subject_type,subject_ref,legal_hold,status "
                            "FROM public.privacy_jobs WHERE tenant_id=:tenant AND id=:id "
                            "FOR UPDATE"
                        ),
                        {"tenant": tenant_id, "id": job_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["status"] == "COMPLETED":
                return
            if row["legal_hold"]:
                await _finish(session, tenant_id, job_id, "HELD", {}, "legal_hold")
                return
            await session.execute(
                text(
                    "UPDATE public.privacy_jobs SET status='STARTED',started_at="
                    "coalesce(started_at,now()),updated_at=now() WHERE tenant_id=:tenant "
                    "AND id=:id AND status IN ('REQUESTED','STARTED')"
                ),
                {"tenant": tenant_id, "id": job_id},
            )
            operation = str(row["operation"])
            subject_type = str(row["subject_type"])
            subject_ref = str(row["subject_ref"])
            if operation == "EXPORT":
                manifest = (
                    await build_export_manifest(
                        session,
                        tenant_id=tenant_id,
                        subject_type=subject_type,
                        subject_ref=subject_ref,
                    )
                ).model_dump(mode="json")
            elif operation == "REVOKE_INTEGRATIONS" and subject_type == "TENANT":
                integrations = await session.execute(
                    text(
                        "UPDATE public.integration_connections SET status='REVOKED',"
                        "credential_secret_id=NULL,granted_scopes='{}',updated_at=now() "
                        "WHERE tenant_id=:tenant AND status<>'REVOKED' RETURNING id"
                    ),
                    {"tenant": tenant_id},
                )
                manifest = {"revoked_integrations": len(integrations.all())}
            elif operation == "DELETE" and subject_type == "CONVERSATION":
                manifest = await _minimize_conversation(
                    session, tenant_id=tenant_id, conversation_ref=subject_ref
                )
            else:
                await _finish(
                    session,
                    tenant_id,
                    job_id,
                    "FAILED",
                    {},
                    "unsupported_privacy_scope",
                )
                return
            await _finish(session, tenant_id, job_id, "COMPLETED", manifest, None)


async def _minimize_conversation(
    session: AsyncSession, *, tenant_id: UUID, conversation_ref: str
) -> dict[str, object]:
    try:
        conversation_id = UUID(conversation_ref)
    except ValueError:
        return {"matched": False, "minimized": 0}
    exists = await session.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM public.conversations WHERE tenant_id=:tenant "
            "AND id=:conversation)"
        ),
        {"tenant": tenant_id, "conversation": conversation_id},
    )
    if not exists:
        return {"matched": False, "minimized": 0}
    message_rows = await session.execute(
        text(
            "UPDATE public.messages SET content='{}',runtime_metadata='{}' WHERE "
            "tenant_id=:tenant AND conversation_id=:conversation RETURNING id"
        ),
        {"tenant": tenant_id, "conversation": conversation_id},
    )
    await session.execute(
        text(
            "UPDATE public.conversations SET customer_wa_id=:pseudonym WHERE tenant_id=:tenant "
            "AND id=:conversation"
        ),
        {
            "tenant": tenant_id,
            "conversation": conversation_id,
            "pseudonym": pseudonymize(str(tenant_id), conversation_ref),
        },
    )
    return {"matched": True, "minimized": len(message_rows.all())}


async def _finish(
    session: AsyncSession,
    tenant_id: UUID,
    job_id: UUID,
    status: str,
    manifest: dict[str, object],
    error_code: str | None,
) -> None:
    await session.execute(
        text(
            "UPDATE public.privacy_jobs SET status=:status,result_manifest=:manifest,"
            "error_code=:error,completed_at=:completed,updated_at=:completed WHERE "
            "tenant_id=:tenant AND id=:id"
        ).bindparams(bindparam("manifest", type_=JSONB)),
        {
            "status": status,
            "manifest": manifest,
            "error": error_code,
            "completed": datetime.now(UTC),
            "tenant": tenant_id,
            "id": job_id,
        },
    )
