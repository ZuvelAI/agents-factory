from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.capabilities.orders.service import OrdersService
from agents_factory.modules.capabilities.returns_claims.configuration import (
    ClaimsConfiguration,
)
from agents_factory.modules.capabilities.returns_claims.models import (
    ApprovedClaimPolicy,
    ClaimDraft,
    ClaimOrderReference,
)
from agents_factory.modules.capabilities.returns_claims.service import (
    ClaimIntakeRejected,
)
from agents_factory.modules.identity.models import IdentityAssessment
from agents_factory.modules.integrations.contracts import ConnectorRequest
from agents_factory.modules.integrations.orders import READS
from agents_factory.modules.knowledge.models import KnowledgeProvenance
from agents_factory.modules.knowledge.repository import KnowledgeRepository


class ClaimSources(Protocol):
    async def identity(
        self,
        configuration: ClaimsConfiguration,
        customer_ref: str,
        action_id: UUID,
        level: int,
    ) -> IdentityAssessment: ...

    async def policy(
        self, configuration: ClaimsConfiguration
    ) -> ApprovedClaimPolicy | None: ...

    async def reference(
        self,
        configuration: ClaimsConfiguration,
        customer_ref: str,
        action_id: UUID,
        draft: ClaimDraft,
    ) -> ClaimOrderReference | None: ...


@dataclass(frozen=True)
class NativeClaimSources:
    context: TenantContext
    sessions: async_sessionmaker[AsyncSession]
    orders: OrdersService
    allow_test: bool = False

    def _scope(self, configuration: ClaimsConfiguration) -> None:
        if (
            self.context.actor_type not in {"system", "platform_admin"}
            or self.context.actor_id is None
            or configuration.binding.tenant_id != self.context.tenant_id
            or self.orders.context.tenant_id != self.context.tenant_id
            or (configuration.environment != "PRODUCTION" and not self.allow_test)
        ):
            raise ClaimIntakeRejected("claim_source_scope_mismatch")

    async def identity(
        self,
        configuration: ClaimsConfiguration,
        customer_ref: str,
        action_id: UUID,
        level: int,
    ) -> IdentityAssessment:
        self._scope(configuration)
        return (
            await self.orders.customer(
                customer_ref, configuration.orders_binding_id, action_id, level
            )
        ).assessment

    async def policy(
        self, configuration: ClaimsConfiguration
    ) -> ApprovedClaimPolicy | None:
        self._scope(configuration)
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await set_tenant_context(session, self.context.tenant_id)
            if await KnowledgeRepository(
                session, self.context
            ).has_open_critical_conflicts(configuration.binding.knowledge_version_id):
                return None
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT d.id, d.source_id, d.source_version_id, d.content_digest, "
                            "s.authority, s.verified_at, s.approved_by_admin_id "
                            "FROM public.knowledge_versions v "
                            "JOIN public.knowledge_version_members m ON m.tenant_id=v.tenant_id AND m.knowledge_version_id=v.id "
                            "JOIN public.knowledge_documents d ON d.tenant_id=m.tenant_id AND d.id=m.document_id "
                            "JOIN public.knowledge_source_versions s ON s.tenant_id=d.tenant_id AND s.id=d.source_version_id AND s.source_id=d.source_id "
                            "WHERE v.tenant_id=:tenant AND v.id=:version AND v.digest=:digest AND v.state=:environment "
                            "AND d.id=:document AND d.content_digest=:document_digest AND d.category='POLICY' "
                            "AND s.authority='AUTHORITATIVE' AND s.approved_by_admin_id IS NOT NULL"
                        ),
                        {
                            "tenant": self.context.tenant_id,
                            "version": configuration.binding.knowledge_version_id,
                            "digest": configuration.binding.knowledge_digest,
                            "environment": configuration.environment,
                            "document": configuration.policy_document_id,
                            "document_digest": configuration.policy_document_digest,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return ApprovedClaimPolicy(
            tenant_id=self.context.tenant_id,
            knowledge_version_id=configuration.binding.knowledge_version_id,
            knowledge_digest=configuration.binding.knowledge_digest,
            document_id=row["id"],
            provenance=KnowledgeProvenance(
                **{
                    key: row[key]
                    for key in (
                        "source_id",
                        "source_version_id",
                        "authority",
                        "verified_at",
                        "approved_by_admin_id",
                        "content_digest",
                    )
                }
            ),
            requirements=configuration.policy_requirements,
        )

    async def reference(
        self,
        configuration: ClaimsConfiguration,
        customer_ref: str,
        action_id: UUID,
        draft: ClaimDraft,
    ) -> ClaimOrderReference | None:
        self._scope(configuration)
        binding = self.orders.binding(configuration.orders_binding_id)
        customer = await self.orders.customer(
            customer_ref, binding.binding_id, action_id, 1
        )
        if not draft.order_id and not draft.purchase_reference:
            return None
        verified = False
        if draft.order_id:
            if READS[1] not in binding.operations:
                raise ClaimIntakeRejected("claim_order_read_unavailable")
            result = await self.orders.connectors(binding).execute(
                ConnectorRequest(
                    tenant_id=self.context.tenant_id,
                    binding_id=binding.binding_id,
                    operation=READS[1],
                    arguments={
                        "order_id": draft.order_id,
                        "customer": customer.match.model_dump(exclude_none=True),
                    },
                )
            )
            # A foreign/missing ID is not downgraded into a verified order claim.
            if result.status != "SUCCEEDED" or result.operation != READS[1]:
                raise ClaimIntakeRejected("claim_order_read_unavailable")
            verified = True
        return ClaimOrderReference(
            tenant_id=self.context.tenant_id,
            customer_ref=customer_ref,
            binding_id=configuration.binding.binding_id,
            resource_id=("order:" + draft.order_id)
            if draft.order_id
            else ("reported:" + str(draft.purchase_reference)),
            order_id=draft.order_id,
            purchase_reference=draft.purchase_reference,
            order_verified=verified,
        )
