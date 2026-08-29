from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.modules.agent_factory.models import (
    AgentSpecConfiguration,
    HumanOperationsConfiguration,
    PersonaConfiguration,
    VersionedDigestReference,
    VersionReference,
)
from agents_factory.modules.agent_factory.repository import AgentSpecRepository
from agents_factory.modules.agent_factory.service import (
    AgentSpecLifecycleService,
    QualityGateEvidence,
)


TENANT_ID = UUID("10000000-0000-0000-0000-000000000012")
CODE_DIGEST = "c" * 64


def context() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_ID,
        actor_id=uuid4(),
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )


def configuration(*, persona_version: str = "1") -> AgentSpecConfiguration:
    return AgentSpecConfiguration(
        product_version="1.0.0",
        persona=PersonaConfiguration(
            version=persona_version,
            instructions=f"Customer Service persona {persona_version}",
        ),
        capabilities=(VersionReference(name="orders", version="1.0.0"),),
        permitted_tools=("orders.get_status",),
        permitted_actions=("orders.cancel",),
        policy=VersionReference(name="customer_service", version="1"),
        identity_policy=VersionReference(name="standard", version="1"),
        approval_routes=VersionReference(name="standard", version="1"),
        knowledge=VersionedDigestReference(
            name="tenant_knowledge", version="1", digest="b" * 64
        ),
        human_operations=HumanOperationsConfiguration(version="1"),
        code_digest=CODE_DIGEST,
    )


class ExactGate:
    async def evaluate(
        self,
        *,
        agent_spec_digest: str,
        knowledge_digest: str,
        code_digest: str,
    ) -> QualityGateEvidence:
        return QualityGateEvidence(
            decision_id=uuid4(),
            passed=True,
            agent_spec_digest=agent_spec_digest,
            knowledge_digest=knowledge_digest,
            code_digest=code_digest,
        )


async def _prepare_admin(session: AsyncSession) -> None:
    await session.execute(text("SET LOCAL ROLE agents_factory_admin"))


@pytest.mark.asyncio
async def test_version_lifecycle_is_immutable_fail_closed_and_rollback_audited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES "
                "(:id, 'task12', 'Task 12')"
            ),
            {"id": TENANT_ID},
        )
        knowledge_version_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO public.knowledge_versions "
                "(id, tenant_id, name, version_number, state) "
                "VALUES (:id, :tenant_id, 'tenant_knowledge', 1, 'DRAFT')"
            ),
            {"id": knowledge_version_id, "tenant_id": TENANT_ID},
        )
        await session.execute(
            text(
                "UPDATE public.knowledge_versions SET state = 'TEST', "
                "digest = :digest WHERE id = :id"
            ),
            {"id": knowledge_version_id, "digest": "b" * 64},
        )

    operation_context = context()
    async with session_factory.begin() as session:
        await _prepare_admin(session)
        repository = AgentSpecRepository(session, operation_context)
        lifecycle = AgentSpecLifecycleService(repository=repository)
        instance, first = await lifecycle.create_instance(configuration=configuration())
        second = await lifecycle.create_draft(
            agent_instance_id=instance.id,
            based_on_version_id=first.id,
            configuration=configuration(persona_version="2"),
        )
        assert (first.version_number, second.version_number) == (1, 2)
        assert first.configuration.persona.version == "1"
        with pytest.raises(DomainError, match="DRAFT to QUALITY_GATE"):
            await lifecycle.enter_quality_gate(second.id)

        first = await lifecycle.promote_to_test(first.id)
        first = await lifecycle.enter_quality_gate(first.id)
        with pytest.raises(DomainError) as blocked:
            await lifecycle.publish_production(first.id)
        assert blocked.value.code == "production_quality_gate_required"
        assert (await repository.get_version(first.id)).state == "QUALITY_GATE"  # type: ignore[union-attr]

        exact_lifecycle = AgentSpecLifecycleService(
            repository=repository,
            quality_gate=ExactGate(),
        )
        first = await exact_lifecycle.publish_production(first.id)
        assert first.state == "PRODUCTION"

        second = await exact_lifecycle.promote_to_test(second.id)
        second = await exact_lifecycle.enter_quality_gate(second.id)
        second = await exact_lifecycle.publish_production(second.id)
        assert second.state == "PRODUCTION"
        rolled_back = await exact_lifecycle.rollback_to(
            agent_instance_id=instance.id,
            target_version_id=first.id,
            current_code_digest=CODE_DIGEST,
        )
        assert rolled_back.id == first.id
        assert (
            await repository.active_version_id(agent_instance_id=instance.id)
            == first.id
        )

        await session.execute(
            text("SELECT set_config('app.environment', 'staging', true)")
        )
        assert (await repository.get_version(first.id)).state == "PRODUCTION"  # type: ignore[union-attr]

    async with session_factory.begin() as session:
        await _prepare_admin(session)
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(TENANT_ID)},
        )
        with pytest.raises(
            DBAPIError, match="Production AgentSpec versions are immutable"
        ):
            await session.execute(
                text(
                    "UPDATE public.agent_spec_versions SET configuration = "
                    "jsonb_set(configuration, '{persona,version}', '\"changed\"') "
                    "WHERE id = :version_id"
                ),
                {"version_id": first.id},
            )

    async with session_factory.begin() as session:
        await _prepare_admin(session)
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(TENANT_ID)},
        )
        actions = tuple(
            (
                await session.execute(
                    text(
                        "SELECT action FROM public.agent_spec_deployments "
                        "ORDER BY created_at, id"
                    )
                )
            ).scalars()
        )
        assert actions == ("PUBLISH", "PUBLISH", "ROLLBACK")
