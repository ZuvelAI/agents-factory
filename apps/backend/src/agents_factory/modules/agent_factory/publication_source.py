"""Resolve source identity separately from privileged checks of editable state."""

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from agents_factory.common.context import TenantContext
from .configuration_models import DraftView
from .configuration_repository import ConfigurationRepository
from .configuration_service import AgentConfigurationService
from .configuration_projection import configuration_digest
from .publication_service import publication_problem
from .workspace_publication_models import PublicationSource
from .workspace_publication_repository import WorkspacePublicationRepository


class PublicationSourceResolver:
    def __init__(self, session: AsyncSession, context: TenantContext):
        self.configurations = ConfigurationRepository(session, context)
        self.publications = WorkspacePublicationRepository(session, context)

    async def editable(
        self,
        agent_id: UUID,
        expected_revision: int,
        expected_company_revision: int | None = None,
    ) -> DraftView:
        # Same order as company refresh: shared profile then per-agent draft.
        profile = await self.configurations.lock_company()
        row = await self.publications.lock_draft(agent_id)
        if profile is None or row is None:
            raise publication_problem(
                "agent_configuration_missing", "Borrador no encontrado.", 404
            )
        draft = AgentConfigurationService.draft_view(row, profile)
        if draft.revision != expected_revision:
            raise publication_problem(
                "configuration_revision_conflict",
                "Recarga el borrador antes de preparar o publicar.",
            )
        if draft.company_update_available or (
            expected_company_revision is not None
            and draft.company_revision != expected_company_revision
        ):
            raise publication_problem(
                "company_snapshot_stale",
                "Incorpora la información actual de la empresa antes de continuar.",
            )
        return draft

    async def resolve(self, version_id: UUID, lock: bool = False) -> PublicationSource:
        row = await self.publications.source(version_id)
        if row is None:
            raise publication_problem(
                "candidate_not_found", "Candidato no encontrado.", 404
            )
        source = PublicationSource.model_validate(row)
        if lock:
            await self.require_current(source, source.revision)
        return source

    async def require_current(
        self, source: PublicationSource, expected_revision: int
    ) -> None:
        if source.source_kind == "LEGACY":
            stored = await self.configurations.lock_legacy()
            if (
                stored is None
                or stored["revision"] != expected_revision
                or source.revision != expected_revision
            ):
                raise publication_problem(
                    "stale_onboarding_revision", "Recarga la configuración guardada."
                )
            return
        draft = await self.editable(
            source.agent_instance_id, expected_revision, source.company_revision
        )
        if (
            source.revision != expected_revision
            or configuration_digest(draft) != source.source_digest
        ):
            raise publication_problem(
                "stale_candidate", "Prepara una versión del borrador actual."
            )
