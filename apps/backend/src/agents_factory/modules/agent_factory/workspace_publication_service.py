"""Prepare exact per-agent candidates without touching channel assignments."""

import re
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from .approved_knowledge import ApprovedKnowledgeRepository
from .configuration_projection import configuration_digest, project_configuration
from .publication_service import publication_problem
from .publication_source import PublicationSourceResolver
from .repository import AgentSpecRepository
from .models import AgentSpecVersion
from .service import AgentSpecLifecycleService
from .workspace_publication_models import WorkspaceCandidateView
from .workspace_publication_repository import WorkspacePublicationRepository


class WorkspacePublicationService:
    def __init__(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        code_digest: str | None,
        compatible_versions: dict[UUID, str] | None = None,
    ):
        self.session, self.context, self.code_digest = session, context, code_digest
        self.compatible_versions = dict(compatible_versions or {})
        self.repository = WorkspacePublicationRepository(session, context)
        self.specs = AgentSpecRepository(session, context)
        self.sources = PublicationSourceResolver(session, context)

    async def prepare(
        self, *, agent_id: UUID, expected_revision: int, expected_company_revision: int
    ) -> WorkspaceCandidateView:
        draft = await self.sources.editable(
            agent_id, expected_revision, expected_company_revision
        )
        if self.code_digest is None or not re.fullmatch(
            r"[0-9a-f]{64}", self.code_digest
        ):
            raise publication_problem(
                "publication_code_missing",
                "Falta la huella verificable del código desplegado.",
            )
        if draft.validation_issues:
            raise publication_problem(
                "publication_configuration_incomplete",
                "Completa los requisitos indicados en el borrador antes de preparar pruebas.",
            )
        version: AgentSpecVersion | None
        row = await self.repository.candidate(
            agent_id, expected_revision, self.code_digest
        )
        if row is None:
            knowledge = await ApprovedKnowledgeRepository(
                self.session, self.context
            ).freeze(draft.configuration.knowledge)
            try:
                configuration = project_configuration(
                    draft, knowledge, self.code_digest
                )
            except ValueError:
                raise publication_problem(
                    "publication_configuration_incomplete",
                    "Revisa la configuración antes de preparar pruebas.",
                ) from None
            base = await self.repository.latest_version(agent_id)
            version = await self.specs.create_draft(
                agent_instance_id=agent_id,
                configuration=configuration,
                based_on_version_id=base,
            )
            version = await AgentSpecLifecycleService(
                repository=self.specs
            ).promote_to_test(version.id)
            row = await self.repository.insert_candidate(
                agent_id=agent_id,
                revision=expected_revision,
                company_revision=draft.company_revision,
                source_digest=configuration_digest(draft),
                code_digest=self.code_digest,
                version_id=version.id,
            )
            await AuditService(self.session).record(
                context=self.context,
                event_type="agent.workspace_candidate_prepared",
                entity_type="agent_spec",
                entity_id=version.id,
                payload={
                    "agent_instance_id": str(agent_id),
                    "revision": expected_revision,
                    "source_digest": row["source_digest"],
                    "digest": version.compiled_digest,
                },
            )
        else:
            version = await self.specs.get_version(row["version_id"])
        if (
            version is None
            or version.compiled_spec is None
            or version.compiled_digest != version.compiled_spec.digest()
        ):
            raise publication_problem(
                "candidate_integrity_failed",
                "El candidato no supera la verificación de integridad.",
            )
        source = await self.sources.resolve(version.id)
        await self.sources.require_current(source, expected_revision)
        return WorkspaceCandidateView(
            version=version, source=source, created_at=row["created_at"]
        )
