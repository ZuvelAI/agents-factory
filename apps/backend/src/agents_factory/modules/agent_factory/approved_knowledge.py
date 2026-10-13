from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.compiler import canonical_json
from agents_factory.modules.agent_factory.models import Sha256Digest
from agents_factory.modules.tenants.onboarding import KnowledgeConfiguration


class ApprovedKnowledgeDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_name: str = Field(min_length=1, max_length=300)
    source_type: Literal["PDF", "WEBSITE", "INTERNAL_TEXT"]
    source_reference: str = Field(min_length=1, max_length=2000)
    authority: Literal["OFFICIAL", "OPERATIONAL", "REFERENCE"]
    approved_summary: str = Field(min_length=1, max_length=10000)
    review_confirmed: Literal[True] = True


class ApprovedKnowledgeSnapshot(ApprovedKnowledgeDocument):
    id: UUID
    tenant_id: UUID
    digest: Sha256Digest
    created_at: datetime


class ApprovedKnowledgeRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def freeze(
        self, configuration: KnowledgeConfiguration
    ) -> ApprovedKnowledgeSnapshot:
        if (
            not configuration.review_confirmed
            or configuration.critical_conflicts != 0
            or any(
                not value.strip()
                for value in (
                    configuration.source_name,
                    configuration.source_reference,
                    configuration.approved_summary,
                )
            )
        ):
            raise ValueError(
                "approved knowledge requires reviewed content and no critical conflicts"
            )
        document = ApprovedKnowledgeDocument(
            **configuration.model_dump(exclude={"critical_conflicts"})
        )
        digest = canonical_json(document).digest
        await set_tenant_context(self._session, self._context.tenant_id)
        await self._session.execute(
            text(
                "INSERT INTO public.agent_approved_knowledge_versions "
                "(id,tenant_id,digest,snapshot) VALUES (:id,:tenant,:digest,:snapshot) "
                "ON CONFLICT (tenant_id,digest) DO NOTHING"
            ).bindparams(bindparam("snapshot", type_=JSONB)),
            {
                "id": uuid4(),
                "tenant": self._context.tenant_id,
                "digest": digest,
                "snapshot": document.model_dump(mode="json"),
            },
        )
        result = await self.get_by_digest(digest)
        if result is None:
            raise RuntimeError("approved knowledge snapshot could not be persisted")
        return result

    async def get_by_digest(self, digest: str) -> ApprovedKnowledgeSnapshot | None:
        await set_tenant_context(self._session, self._context.tenant_id)
        result = await self._session.execute(
            text(
                "SELECT id,tenant_id,digest,snapshot,created_at "
                "FROM public.agent_approved_knowledge_versions "
                "WHERE tenant_id=:tenant AND digest=:digest"
            ),
            {"tenant": self._context.tenant_id, "digest": digest},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        document = ApprovedKnowledgeDocument.model_validate(row["snapshot"])
        if canonical_json(document).digest != row["digest"]:
            raise RuntimeError("approved knowledge digest does not match content")
        return ApprovedKnowledgeSnapshot(
            **document.model_dump(),
            id=row["id"],
            tenant_id=row["tenant_id"],
            digest=row["digest"],
            created_at=row["created_at"],
        )
