"""Administrative draft use cases. Never compile, bind, publish or call providers."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal
from agents_factory.database import set_tenant_context
from agents_factory.modules.tenants.models import Tenant
from agents_factory.modules.tenants.repository import TenantRepository
from agents_factory.modules.tenants.onboarding import (
    CompanyConfiguration,
    OnboardingConfiguration,
)
from .onboarding_projection import projection_blockers
from .configuration_models import (
    AgentEditableConfiguration,
    CompanyProfileView,
    DraftView,
    ValidationIssue,
)
from .configuration_repository import ConfigurationRepository
from .publication_service import publication_problem
from .repository import AgentSpecRepository


class AgentConfigurationService:
    def __init__(self, session: AsyncSession, principal: AdminPrincipal) -> None:
        self.session, self.principal = session, principal

    def context(self, tenant_id: UUID) -> TenantContext:
        return TenantContext(
            tenant_id, self.principal.user_id, "platform_admin", uuid4()
        )

    async def scope(
        self, tenant_id: UUID, agent_id: UUID | None = None
    ) -> ConfigurationRepository:
        await set_tenant_context(self.session, tenant_id)
        if await TenantRepository(self.session).get(tenant_id) is None:
            raise publication_problem(
                "configuration_not_found", "Empresa o agente no encontrado.", 404
            )
        context = self.context(tenant_id)
        if (
            agent_id is not None
            and await AgentSpecRepository(self.session, context).get_instance(agent_id)
            is None
        ):
            raise publication_problem(
                "configuration_not_found", "Empresa o agente no encontrado.", 404
            )
        return ConfigurationRepository(self.session, context)

    async def audit(
        self,
        tenant_id: UUID,
        entity_id: UUID,
        event: str,
        revision: int,
        sections: list[str],
    ) -> None:
        await AuditService(self.session).record(
            context=self.context(tenant_id),
            event_type=event,
            entity_type="agent_configuration"
            if entity_id != tenant_id
            else "company_profile",
            entity_id=entity_id,
            payload={
                "previous_revision": revision - 1,
                "revision": revision,
                "sections": sections,
            },
        )

    @staticmethod
    def conflict() -> None:
        raise publication_problem(
            "configuration_revision_conflict",
            "La configuración cambió. Recarga para comparar antes de guardar.",
            409,
        )

    async def create_company(self, *, name: str, slug: str) -> CompanyProfileView:
        tenant = Tenant.new(name=name, slug=slug)
        await set_tenant_context(self.session, tenant.id)
        try:
            async with self.session.begin_nested():
                await TenantRepository(self.session).create(tenant)
        except IntegrityError:
            raise publication_problem(
                "company_slug_conflict",
                "El identificador de empresa ya está en uso.",
                409,
            ) from None
        row = await ConfigurationRepository(
            self.session, self.context(tenant.id)
        ).insert_company(
            CompanyConfiguration(commercial_name=name).model_dump(mode="json")
        )
        assert row is not None
        await self.audit(
            tenant.id, tenant.id, "company.profile_created", 1, ["company"]
        )
        return CompanyProfileView.model_validate(
            {k: row[k] for k in CompanyProfileView.model_fields}
        )

    async def get_company(self, *, tenant_id: UUID) -> CompanyProfileView:
        row = await (await self.scope(tenant_id)).read_company()
        if row is None:
            raise publication_problem(
                "company_profile_missing",
                "Completa o importa los datos de la empresa.",
                404,
            )
        return self.company_view(row)

    @staticmethod
    def company_view(row: dict[str, Any]) -> CompanyProfileView:
        return CompanyProfileView.model_validate(
            {k: row[k] for k in CompanyProfileView.model_fields}
        )

    async def save_company(
        self,
        *,
        tenant_id: UUID,
        expected_revision: int,
        configuration: CompanyConfiguration,
    ) -> CompanyProfileView:
        repository = await self.scope(tenant_id)
        if not configuration.commercial_name:
            raise publication_problem(
                "company_name_required", "Indica el nombre comercial.", 422
            )
        data = configuration.model_dump(mode="json")
        row = (
            await repository.insert_company(data)
            if expected_revision == 0
            else await repository.update_company(
                expected_revision=expected_revision, configuration=data
            )
        )
        if row is None:
            self.conflict()
        assert row is not None
        await repository.update_company_name(configuration.commercial_name)
        await self.audit(
            tenant_id, tenant_id, "company.profile_saved", row["revision"], ["company"]
        )
        return self.company_view(row)

    async def create_agent(self, *, tenant_id: UUID, name: str) -> DraftView:
        repository = await self.scope(tenant_id)
        profile = await repository.lock_company()
        if profile is None:
            raise publication_problem(
                "company_profile_missing",
                "Completa los datos de la empresa antes de crear agentes.",
                409,
            )
        agent = await AgentSpecRepository(
            self.session, self.context(tenant_id)
        ).create_instance()
        config = AgentEditableConfiguration()
        config.agent.agent_name = name
        row = await repository.insert_draft(
            agent_id=agent.id,
            company_revision=profile["revision"],
            company_snapshot=profile["configuration"],
            configuration=config.model_dump(mode="json"),
            provenance={"source": "manual"},
        )
        assert row is not None
        await self.audit(
            tenant_id, agent.id, "agent.configuration_created", 1, ["agent"]
        )
        return self.draft_view(row, profile)

    @staticmethod
    def draft_view(row: dict[str, Any], profile: dict[str, Any]) -> DraftView:
        config = AgentEditableConfiguration.model_validate(row["configuration"])
        issues = []
        for field, value in (
            ("agent.greeting", config.agent.greeting),
            ("agent.instructions", config.agent.instructions),
            ("knowledge.approved_summary", config.knowledge.approved_summary),
            ("agent.supported_languages", config.agent.supported_languages),
            ("knowledge.source_name", config.knowledge.source_name),
            ("knowledge.source_reference", config.knowledge.source_reference),
        ):
            if not value:
                issues.append(
                    ValidationIssue(
                        field=field,
                        code="required_before_test",
                        message="Completa este campo antes de preparar pruebas.",
                    )
                )
        if not config.knowledge.review_confirmed:
            issues.append(
                ValidationIssue(
                    field="knowledge.review_confirmed",
                    code="review_required",
                    message="El conocimiento requiere revisión.",
                )
            )
        if config.knowledge.critical_conflicts:
            issues.append(
                ValidationIssue(
                    field="knowledge.critical_conflicts",
                    code="unresolved_conflicts",
                    message="Resuelve los conflictos críticos de conocimiento antes de preparar pruebas.",
                )
            )
        combined = OnboardingConfiguration.model_validate(
            {
                "company": row["company_snapshot"],
                **config.model_dump(
                    mode="json", exclude={"schema_version", "purpose", "lead_capture"}
                ),
            }
        )
        issues.extend(
            ValidationIssue(
                field=f"operation.{index}",
                code="unsupported_configuration",
                message=message,
            )
            for index, message in enumerate(projection_blockers(combined))
        )
        return DraftView(
            **{
                k: row[k]
                for k in (
                    "tenant_id",
                    "agent_instance_id",
                    "revision",
                    "company_revision",
                    "company_snapshot",
                    "configuration",
                    "provenance",
                    "updated_at",
                )
            },
            current_company_revision=profile["revision"],
            company_update_available=profile["revision"] != row["company_revision"],
            validation_issues=issues,
        )

    async def get_draft(self, *, tenant_id: UUID, agent_id: UUID) -> DraftView:
        repository = await self.scope(tenant_id, agent_id)
        row, profile = (
            await repository.read_draft(agent_id),
            await repository.read_company(),
        )
        if row is None or profile is None:
            raise publication_problem(
                "agent_configuration_missing",
                "Crea o importa un borrador explícitamente.",
                404,
            )
        return self.draft_view(row, profile)

    async def save_draft(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        expected_revision: int,
        configuration: AgentEditableConfiguration,
    ) -> DraftView:
        repository = await self.scope(tenant_id, agent_id)
        before = await self.get_draft(tenant_id=tenant_id, agent_id=agent_id)
        if (
            before.configuration.capabilities != configuration.capabilities
            or before.configuration.integrations != configuration.integrations
        ):
            raise publication_problem(
                "configuration_tools_read_only",
                "Las herramientas se habilitarán en su fase de integración.",
                422,
            )
        row = await repository.update_draft(
            agent_id=agent_id,
            expected_revision=expected_revision,
            configuration=configuration.model_dump(mode="json"),
        )
        if row is None:
            self.conflict()
        assert row is not None
        previous_data, next_data = (
            before.configuration.model_dump(),
            configuration.model_dump(),
        )
        changed = [
            key
            for key in sorted(previous_data.keys() | next_data.keys())
            if previous_data.get(key) != next_data.get(key)
        ]
        await self.audit(
            tenant_id, agent_id, "agent.configuration_saved", row["revision"], changed
        )
        profile = await repository.read_company()
        assert profile is not None
        return self.draft_view(row, profile)

    async def refresh_company(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        expected_revision: int,
        expected_company_revision: int,
    ) -> DraftView:
        repository = await self.scope(tenant_id, agent_id)
        profile = await repository.lock_company()
        if profile is None or profile["revision"] != expected_company_revision:
            self.conflict()
        assert profile is not None
        row = await repository.refresh_company(
            agent_id=agent_id,
            expected_revision=expected_revision,
            company_revision=profile["revision"],
            company_snapshot=profile["configuration"],
        )
        if row is None:
            self.conflict()
        assert row is not None
        await self.audit(
            tenant_id,
            agent_id,
            "agent.company_snapshot_refreshed",
            row["revision"],
            ["company_snapshot"],
        )
        return self.draft_view(row, profile)
