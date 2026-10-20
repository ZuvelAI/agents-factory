"""Read-only, tenant-first SQL and filter-bound keyset cursors."""

import hashlib
import json
from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.engine import RowMapping

from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.publication_service import publication_problem
from .read_models import (
    ProspectDetail,
    ProspectEvent,
    ProspectEventPage,
    ProspectPage,
    ProspectSummary,
)

_SUMMARY = """
SELECT p.id,p.tenant_id,p.contact_name,p.contact_username,p.declared_company,p.service_interests,p.need_summary,p.status,
 p.first_conversation_id,p.last_conversation_id,p.created_at,p.updated_at,s.capture_suppressed,
 (SELECT value FROM public.lead_subject_keys k WHERE k.tenant_id=p.tenant_id AND k.subject_id=p.subject_id AND k.kind='PHONE' ORDER BY k.created_at DESC,k.id DESC LIMIT 1) AS phone_number,
 EXISTS(SELECT 1 FROM public.lead_capture_events conflict WHERE conflict.tenant_id=p.tenant_id AND conflict.operation='CONFLICT'
   AND conflict.changes->'conflicting_subject_ids' @> jsonb_build_array(p.subject_id::text)) AS identity_conflict
FROM public.lead_prospects p JOIN public.lead_subjects s ON s.tenant_id=p.tenant_id AND s.id=p.subject_id
WHERE p.tenant_id=:tenant AND (CAST(:selected AS uuid) IS NULL OR p.id=:selected)
AND (CAST(:agent AS uuid) IS NULL OR EXISTS(SELECT 1 FROM public.lead_capture_events e WHERE e.tenant_id=p.tenant_id AND e.prospect_id=p.id AND e.agent_instance_id=:agent))
AND (CAST(:pattern AS text) IS NULL OR p.contact_name ILIKE :pattern OR p.contact_username ILIKE :pattern OR p.declared_company ILIKE :pattern
 OR EXISTS(SELECT 1 FROM public.lead_subject_keys k WHERE k.tenant_id=p.tenant_id AND k.subject_id=p.subject_id AND k.kind='PHONE' AND k.value ILIKE :pattern))
AND (CAST(:at AS timestamptz) IS NULL OR (p.updated_at,p.id)<(:at,:after))
ORDER BY p.updated_at DESC,p.id DESC LIMIT :limit
"""


def _scope_key(*values: object) -> str:
    return hashlib.sha256(
        json.dumps(values, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _cursor(scope: str, at: datetime, identity: UUID) -> str:
    return urlsafe_b64encode(
        json.dumps(
            {"scope": scope, "at": at.isoformat(), "id": str(identity)},
            separators=(",", ":"),
        ).encode()
    ).decode()


def _decode(value: str | None, scope: str) -> tuple[datetime | None, UUID | None]:
    if value is None:
        return None, None
    try:
        if len(value) > 512:
            raise ValueError
        data = json.loads(b64decode(value, altchars=b"-_", validate=True))
        if not isinstance(data, dict) or set(data) != {"scope", "at", "id"}:
            raise ValueError
        at, identity = datetime.fromisoformat(data["at"]), UUID(data["id"])
        if at.tzinfo is None:
            raise ValueError
        if data["scope"] != scope:
            raise publication_problem(
                "prospect_not_found", "Recurso no encontrado.", 404
            )
        return at, identity
    except (ValueError, TypeError, UnicodeError, Base64Error):
        raise publication_problem(
            "invalid_prospect_cursor", "Cursor inválido.", 422
        ) from None


class LeadReadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _scope(self, tenant: UUID, agent: UUID | None = None) -> None:
        await set_tenant_context(self.session, tenant)
        exists = await self.session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM public.tenants WHERE id=:tenant) AND (CAST(:agent AS uuid) IS NULL OR EXISTS(SELECT 1 FROM public.agent_instances WHERE tenant_id=:tenant AND id=:agent))"
            ),
            {"tenant": tenant, "agent": agent},
        )
        if not exists:
            raise publication_problem(
                "prospect_not_found", "Recurso no encontrado.", 404
            )

    async def _rows(
        self,
        tenant: UUID,
        *,
        agent: UUID | None = None,
        selected: UUID | None = None,
        q: str | None = None,
        at: datetime | None = None,
        after: UUID | None = None,
        limit: int = 21,
    ) -> list[RowMapping]:
        pattern = (
            None
            if not q
            else "%"
            + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        return list(
            (
                await self.session.execute(
                    text(_SUMMARY),
                    {
                        "tenant": tenant,
                        "agent": agent,
                        "selected": selected,
                        "pattern": pattern,
                        "at": at,
                        "after": after,
                        "limit": limit,
                    },
                )
            )
            .mappings()
            .all()
        )

    async def list(
        self,
        tenant: UUID,
        *,
        agent: UUID | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ProspectPage:
        await self._scope(tenant, agent)
        q = q.strip() if q else None
        scope = _scope_key("prospects", tenant, agent, q)
        at, after = _decode(cursor, scope)
        if after and not await self._rows(
            tenant, agent=agent, selected=after, q=q, limit=1
        ):
            raise publication_problem(
                "prospect_not_found", "Recurso no encontrado.", 404
            )
        data = await self._rows(
            tenant, agent=agent, q=q, at=at, after=after, limit=limit + 1
        )
        return ProspectPage(
            items=[ProspectSummary(**r) for r in data[:limit]],
            next_cursor=_cursor(
                scope, data[limit - 1]["updated_at"], data[limit - 1]["id"]
            )
            if len(data) > limit
            else None,
        )

    async def get(
        self, tenant: UUID, identity: UUID, agent: UUID | None = None
    ) -> ProspectSummary:
        await self._scope(tenant, agent)
        data = await self._rows(tenant, agent=agent, selected=identity, limit=1)
        if not data:
            raise publication_problem(
                "prospect_not_found", "Recurso no encontrado.", 404
            )
        return ProspectSummary(**data[0])

    async def detail(
        self, tenant: UUID, identity: UUID, agent: UUID | None = None
    ) -> ProspectDetail:
        summary = await self.get(tenant, identity, agent)
        return ProspectDetail(
            prospect=summary, events=await self.events(tenant, identity)
        )

    async def events(
        self,
        tenant: UUID,
        identity: UUID,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ProspectEventPage:
        await self.get(tenant, identity)
        scope = _scope_key("prospect-events", tenant, identity)
        at, after = _decode(cursor, scope)
        sql = """SELECT e.id,e.conversation_id,e.inbound_message_id,e.agent_instance_id,e.agent_version_id,
        v.version_number,v.configuration->>'agent_display_name' AS agent_name,e.operation,e.evidence,e.created_at,
        coalesce(e.changes->'transcription_sources','[]'::jsonb) AS transcription_sources
        FROM public.lead_capture_events e JOIN public.lead_prospects p ON p.tenant_id=e.tenant_id
        JOIN public.agent_spec_versions v ON v.tenant_id=e.tenant_id AND v.agent_instance_id=e.agent_instance_id AND v.id=e.agent_version_id
        WHERE e.tenant_id=:tenant AND p.id=:prospect AND (e.prospect_id=p.id OR e.changes->'conflicting_subject_ids' @> jsonb_build_array(p.subject_id::text))
        AND (CAST(:at AS timestamptz) IS NULL OR (e.created_at,e.id)<(:at,:after))
        ORDER BY e.created_at DESC,e.id DESC LIMIT :limit"""
        if after:
            anchor = await self.session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM public.lead_capture_events e JOIN public.lead_prospects p ON p.tenant_id=e.tenant_id WHERE e.tenant_id=:tenant AND p.id=:prospect AND e.id=:after AND (e.prospect_id=p.id OR e.changes->'conflicting_subject_ids' @> jsonb_build_array(p.subject_id::text)))"
                ),
                {"tenant": tenant, "prospect": identity, "after": after},
            )
            if not anchor:
                raise publication_problem(
                    "prospect_not_found", "Recurso no encontrado.", 404
                )
        data = (
            (
                await self.session.execute(
                    text(sql),
                    {
                        "tenant": tenant,
                        "prospect": identity,
                        "at": at,
                        "after": after,
                        "limit": limit + 1,
                    },
                )
            )
            .mappings()
            .all()
        )
        return ProspectEventPage(
            items=[ProspectEvent(**r) for r in data[:limit]],
            next_cursor=_cursor(
                scope, data[limit - 1]["created_at"], data[limit - 1]["id"]
            )
            if len(data) > limit
            else None,
        )

    async def for_conversation(
        self, tenant: UUID, conversation: UUID
    ) -> ProspectSummary | None:
        await self._scope(tenant)
        exists = await self.session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM public.conversations WHERE tenant_id=:tenant AND id=:id)"
            ),
            {"tenant": tenant, "id": conversation},
        )
        if not exists:
            raise publication_problem(
                "prospect_not_found", "Recurso no encontrado.", 404
            )
        identity = await self.session.scalar(
            text(
                "SELECT prospect_id FROM public.lead_capture_events WHERE tenant_id=:tenant AND conversation_id=:conversation AND prospect_id IS NOT NULL ORDER BY created_at DESC,id DESC LIMIT 1"
            ),
            {"tenant": tenant, "conversation": conversation},
        )
        return None if identity is None else await self.get(tenant, identity)
