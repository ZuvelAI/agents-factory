from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.compiler import CompiledAgentSpec
from agents_factory.modules.agent_factory.models import (
    AgentInstance,
    AgentSpecConfiguration,
    AgentSpecDeployment,
    AgentSpecDraft,
    AgentSpecVersion,
    DeploymentAction,
)
from agents_factory.modules.runtime.contracts import AgentSpecSnapshot


class AgentSpecRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def create_instance(self) -> AgentInstance:
        await self._scope()
        result = await self._session.execute(
            text(
                "INSERT INTO public.agent_instances (id, tenant_id, product) "
                "VALUES (:id, :tenant_id, 'Agent Customer Service') "
                "RETURNING id, tenant_id, product, created_at, updated_at"
            ),
            {"id": new_uuid7(), "tenant_id": self._context.tenant_id},
        )
        return AgentInstance.from_mapping(result.mappings().one())

    async def get_instance(self, agent_instance_id: UUID) -> AgentInstance | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, product, created_at, updated_at "
                "FROM public.agent_instances "
                "WHERE tenant_id = :tenant_id AND id = :instance_id"
            ),
            {"tenant_id": self._context.tenant_id, "instance_id": agent_instance_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else AgentInstance.from_mapping(row)

    async def create_draft(
        self,
        *,
        agent_instance_id: UUID,
        configuration: AgentSpecConfiguration,
        based_on_version_id: UUID | None,
    ) -> AgentSpecVersion:
        await self._scope()
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": str(agent_instance_id)},
        )
        statement = text(
            "INSERT INTO public.agent_spec_versions "
            "(id, tenant_id, agent_instance_id, version_number, state, "
            "based_on_version_id, configuration) "
            "SELECT :id, :tenant_id, :instance_id, "
            "coalesce(max(version_number), 0) + 1, 'DRAFT', :based_on, :configuration "
            "FROM public.agent_spec_versions "
            "WHERE tenant_id = :tenant_id AND agent_instance_id = :instance_id "
            "RETURNING id, tenant_id, agent_instance_id, version_number, state, "
            "based_on_version_id, configuration, compiled_spec, compiled_digest, "
            "created_at, updated_at"
        ).bindparams(bindparam("configuration", type_=JSONB))
        result = await self._session.execute(
            statement,
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "instance_id": agent_instance_id,
                "based_on": based_on_version_id,
                "configuration": configuration.model_dump(mode="json"),
            },
        )
        return AgentSpecVersion.from_mapping(result.mappings().one())

    async def get_version(self, version_id: UUID) -> AgentSpecVersion | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, agent_instance_id, version_number, state, "
                "based_on_version_id, configuration, compiled_spec, compiled_digest, "
                "created_at, updated_at FROM public.agent_spec_versions "
                "WHERE tenant_id = :tenant_id AND id = :version_id"
            ),
            {"tenant_id": self._context.tenant_id, "version_id": version_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else AgentSpecVersion.from_mapping(row)

    async def get_draft(
        self, *, agent_instance_id: UUID, draft_version_id: UUID
    ) -> AgentSpecDraft | None:
        version = await self.get_version(draft_version_id)
        if (
            version is None
            or version.agent_instance_id != agent_instance_id
            or version.state != "DRAFT"
        ):
            return None
        return version.as_draft()

    async def has_deployable_knowledge_binding(
        self, *, name: str, version: str, digest: str
    ) -> bool:
        await self._scope()
        if not version.isdecimal():
            return False
        exists = await self._session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM public.knowledge_versions "
                "WHERE tenant_id = :tenant_id AND name = :name "
                "AND version_number = :version_number AND digest = :digest "
                "AND state IN ('TEST', 'PRODUCTION'))"
            ),
            {
                "tenant_id": self._context.tenant_id,
                "name": name,
                "version_number": int(version),
                "digest": digest,
            },
        )
        return bool(exists)

    async def promote_draft_to_test(
        self, *, version_id: UUID, compiled: CompiledAgentSpec
    ) -> AgentSpecVersion | None:
        await self._scope()
        statement = text(
            "UPDATE public.agent_spec_versions SET state = 'TEST', "
            "compiled_spec = :compiled_spec, compiled_digest = :compiled_digest, "
            "updated_at = now() WHERE tenant_id = :tenant_id AND id = :version_id "
            "AND state = 'DRAFT' RETURNING id, tenant_id, agent_instance_id, "
            "version_number, state, based_on_version_id, configuration, "
            "compiled_spec, compiled_digest, created_at, updated_at"
        ).bindparams(bindparam("compiled_spec", type_=JSONB))
        result = await self._session.execute(
            statement,
            {
                "tenant_id": self._context.tenant_id,
                "version_id": version_id,
                "compiled_spec": compiled.spec.model_dump(mode="json"),
                "compiled_digest": compiled.digest,
            },
        )
        row = result.mappings().one_or_none()
        return None if row is None else AgentSpecVersion.from_mapping(row)

    async def enter_quality_gate(self, version_id: UUID) -> AgentSpecVersion | None:
        return await self._transition(
            version_id=version_id,
            expected="TEST",
            target="QUALITY_GATE",
        )

    async def publish(
        self,
        *,
        version_id: UUID,
        decision_id: UUID,
        published_at: datetime,
    ) -> AgentSpecVersion | None:
        version = await self._transition(
            version_id=version_id,
            expected="QUALITY_GATE",
            target="PRODUCTION",
        )
        if version is None or version.compiled_digest is None:
            return None
        await self.append_deployment(
            version=version,
            action="PUBLISH",
            decision_id=decision_id,
            replaced_version_id=await self.active_version_id(
                agent_instance_id=version.agent_instance_id
            ),
            created_at=published_at,
        )
        return version

    async def append_deployment(
        self,
        *,
        version: AgentSpecVersion,
        action: DeploymentAction,
        decision_id: UUID,
        replaced_version_id: UUID | None,
        created_at: datetime,
    ) -> AgentSpecDeployment:
        if version.compiled_digest is None:
            raise ValueError("deployment requires a compiled AgentSpec")
        result = await self._session.execute(
            text(
                "INSERT INTO public.agent_spec_deployments "
                "(id, tenant_id, agent_instance_id, version_id, action, "
                "replaced_version_id, agent_spec_digest, knowledge_digest, "
                "code_digest, quality_gate_decision_id, created_at) VALUES "
                "(:id, :tenant_id, :instance_id, :version_id, :action, :replaced, "
                ":spec_digest, :knowledge_digest, :code_digest, :decision_id, "
                ":created_at) RETURNING id, tenant_id, agent_instance_id, "
                "version_id, action, replaced_version_id, agent_spec_digest, "
                "knowledge_digest, code_digest, quality_gate_decision_id, created_at"
            ),
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "instance_id": version.agent_instance_id,
                "version_id": version.id,
                "action": action,
                "replaced": replaced_version_id,
                "spec_digest": version.compiled_digest,
                "knowledge_digest": version.configuration.knowledge.digest,
                "code_digest": version.configuration.code_digest,
                "decision_id": decision_id,
                "created_at": created_at,
            },
        )
        return AgentSpecDeployment.model_validate(result.mappings().one())

    async def active_version_id(self, *, agent_instance_id: UUID) -> UUID | None:
        await self._scope()
        return cast(
            UUID | None,
            await self._session.scalar(
                text(
                    "SELECT version_id FROM public.agent_spec_deployments "
                    "WHERE tenant_id = :tenant_id "
                    "AND agent_instance_id = :instance_id "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {
                    "tenant_id": self._context.tenant_id,
                    "instance_id": agent_instance_id,
                },
            ),
        )

    async def active_version(
        self, *, agent_instance_id: UUID
    ) -> AgentSpecVersion | None:
        version_id = await self.active_version_id(agent_instance_id=agent_instance_id)
        return None if version_id is None else await self.get_version(version_id)

    async def original_deployment(
        self, *, version_id: UUID
    ) -> AgentSpecDeployment | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, agent_instance_id, version_id, action, "
                "replaced_version_id, agent_spec_digest, knowledge_digest, "
                "code_digest, quality_gate_decision_id, created_at "
                "FROM public.agent_spec_deployments WHERE tenant_id = :tenant_id "
                "AND version_id = :version_id AND action = 'PUBLISH' "
                "ORDER BY created_at, id LIMIT 1"
            ),
            {"tenant_id": self._context.tenant_id, "version_id": version_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else AgentSpecDeployment.model_validate(row)

    async def _transition(
        self, *, version_id: UUID, expected: str, target: str
    ) -> AgentSpecVersion | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "UPDATE public.agent_spec_versions SET state = :target, "
                "updated_at = now() WHERE tenant_id = :tenant_id "
                "AND id = :version_id AND state = :expected RETURNING id, "
                "tenant_id, agent_instance_id, version_number, state, "
                "based_on_version_id, configuration, compiled_spec, "
                "compiled_digest, created_at, updated_at"
            ),
            {
                "target": target,
                "tenant_id": self._context.tenant_id,
                "version_id": version_id,
                "expected": expected,
            },
        )
        row = result.mappings().one_or_none()
        return None if row is None else AgentSpecVersion.from_mapping(row)

    async def _scope(self) -> None:
        await set_tenant_context(self._session, self._context.tenant_id)


class ProductionAgentSpecProvider:
    """Explicit runtime projection for one bound Agent Instance.

    A Draft or Test version is never selected implicitly. Task 12 leaves the
    existing Milestone 2 provider wiring unchanged until a channel is bound to
    a Production deployment.
    """

    def __init__(self, session: AsyncSession, *, agent_instance_id: UUID) -> None:
        self._session = session
        self._agent_instance_id = agent_instance_id

    async def get_active(self, *, tenant_id: UUID) -> AgentSpecSnapshot | None:
        await set_tenant_context(self._session, tenant_id)
        result = await self._session.execute(
            text(
                "SELECT version.compiled_spec, version.compiled_digest "
                "FROM public.agent_spec_deployments AS deployment "
                "JOIN public.agent_spec_versions AS version "
                "ON version.tenant_id = deployment.tenant_id "
                "AND version.agent_instance_id = deployment.agent_instance_id "
                "AND version.id = deployment.version_id "
                "WHERE deployment.tenant_id = :tenant_id "
                "AND deployment.agent_instance_id = :instance_id "
                "AND version.state = 'PRODUCTION' "
                "ORDER BY deployment.created_at DESC, deployment.id DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "instance_id": self._agent_instance_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        from agents_factory.modules.agent_factory.models import AgentSpec

        spec = AgentSpec.model_validate(row["compiled_spec"])
        snapshot = spec.to_runtime_snapshot(active=True)
        if snapshot.digest != row["compiled_digest"]:
            raise RuntimeError("persisted AgentSpec digest does not match its document")
        return snapshot
