"""Prepare exact per-agent candidates without touching channel assignments."""

import re
from typing import Any
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
from .channel_binding import AccountAgentBinding
from .workspace_publication_views import WorkspacePublicationState


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

    async def publish(
        self,
        *,
        agent_id: UUID,
        expected_revision: int,
        version_id: UUID,
        test_run_id: UUID,
        whatsapp_account_id: UUID,
        expected_binding_revision: int,
        expected_current_agent_id: UUID | None,
        confirm_publish: bool,
    ) -> AccountAgentBinding:
        from .channel_binding import AccountAgentBindingRepository
        from .publication_evidence import WorkspacePublicationEvidenceService
        from .workspace_publication_gate import WorkspaceQualityGate

        if not confirm_publish:
            raise publication_problem(
                "publication_confirmation_required",
                "Confirma el número y la versión destino.",
                422,
            )
        await self.sources.editable(agent_id, expected_revision)
        source = await self.sources.resolve(version_id)
        if (
            source.source_kind != "AGENT_CONFIGURATION"
            or source.agent_instance_id != agent_id
        ):
            raise publication_problem(
                "candidate_not_found", "Candidato no encontrado.", 404
            )
        await self.sources.require_current(source, expected_revision)
        if self.code_digest is None or source.code_digest != self.code_digest:
            raise publication_problem(
                "stale_candidate", "Prepara una versión para el código actual."
            )
        account = await self.repository.lock_account(whatsapp_account_id)
        if account is None:
            raise publication_problem(
                "whatsapp_account_not_found", "Cuenta no encontrada.", 404
            )
        if account["status"] != "active" or account["health_status"] != "HEALTHY":
            raise publication_problem(
                "whatsapp_account_unhealthy",
                "La cuenta requiere revisión antes de publicar.",
            )
        bindings = AccountAgentBindingRepository(self.session, self.context)
        current = await bindings.get_for_account(whatsapp_account_id)
        if (
            0 if current is None else current.revision
        ) != expected_binding_revision or (
            None if current is None else current.agent_instance_id
        ) != expected_current_agent_id:
            raise publication_problem(
                "stale_account_binding",
                "La asignación cambió; revisa de nuevo el destino.",
            )
        run = await WorkspacePublicationEvidenceService(
            self.session, self.context, code_digest=self.code_digest
        ).read(agent_id, test_run_id)
        version = await self.specs.get_version(version_id)
        if (
            version is None
            or run.version_id != version_id
            or version.compiled_spec is None
            or version.compiled_digest != version.compiled_spec.digest()
        ):
            raise publication_problem(
                "candidate_integrity_failed",
                "El candidato y su evidencia no coinciden.",
            )
        gate = WorkspaceQualityGate(
            self.session,
            self.context,
            agent_id=agent_id,
            run_id=test_run_id,
            expected_revision=expected_revision,
            code_digest=self.code_digest,
        )
        if (
            await gate.evaluate(
                agent_spec_digest=version.compiled_digest,
                knowledge_digest=version.configuration.knowledge.digest,
                code_digest=self.code_digest,
            )
            is None
        ):
            raise publication_problem(
                "production_quality_gate_required",
                "Se requieren pruebas vigentes revisadas y aprobadas.",
            )
        lifecycle = AgentSpecLifecycleService(repository=self.specs, quality_gate=gate)
        if version.state == "TEST":
            version = await lifecycle.enter_quality_gate(version_id)
        if version.state != "PRODUCTION":
            version = await lifecycle.publish_production(version_id)
        binding = await bindings.bind(
            whatsapp_account_id,
            version,
            expected_revision=expected_binding_revision,
            action="PUBLISH",
        )
        await AuditService(self.session).record(
            context=self.context,
            event_type="agent.account_published",
            entity_type="whatsapp_account",
            entity_id=whatsapp_account_id,
            payload={
                "version_id": str(version_id),
                "agent_instance_id": str(agent_id),
                "binding_revision": binding.revision,
            },
        )
        return binding

    async def rollback(
        self,
        *,
        agent_id: UUID,
        whatsapp_account_id: UUID,
        target_version_id: UUID,
        expected_binding_revision: int,
        confirm_rollback: bool,
    ) -> AccountAgentBinding:
        from .publication_service import PanelPublicationService

        if not confirm_rollback:
            raise publication_problem(
                "rollback_confirmation_required",
                "Confirma la recuperación de versión.",
                422,
            )
        current = await self.repository.binding_for_account(whatsapp_account_id)
        if current is None or current["agent_instance_id"] != agent_id:
            raise publication_problem(
                "whatsapp_account_not_found", "Cuenta del agente no encontrada.", 404
            )
        return await PanelPublicationService(
            self.session,
            self.context,
            code_digest=self.code_digest,
            compatible_versions=self.compatible_versions,
        ).rollback(
            whatsapp_account_id=whatsapp_account_id,
            target_version_id=target_version_id,
            expected_binding_revision=expected_binding_revision,
        )

    async def read_state(
        self,
        agent_id: UUID,
        *,
        cursor: str | None = None,
        limit: int = 20,
        section: str = "candidates",
    ) -> WorkspacePublicationState:
        from .configuration_repository import ConfigurationRepository
        from .configuration_service import AgentConfigurationService
        from .workspace_cursor import decode_activity_cursor, encode_activity_cursor
        from .publication_evidence import WorkspacePublicationEvidenceService

        if await self.specs.get_instance(agent_id) is None:
            raise publication_problem(
                "agent_configuration_missing", "Agente no encontrado.", 404
            )
        configs = ConfigurationRepository(self.session, self.context)
        row, profile = await configs.read_draft(agent_id), await configs.read_company()
        blockers = []
        draft = (
            None
            if row is None or profile is None
            else AgentConfigurationService.draft_view(row, profile)
        )
        if draft is None:
            blockers.append("Crea o importa un borrador antes de preparar pruebas.")
        else:
            blockers.extend(issue.message for issue in draft.validation_issues)
            if draft.company_update_available:
                blockers.append("Incorpora la información actual de la empresa.")
        if not self.code_digest:
            blockers.append("Falta la huella verificable del código desplegado.")
        at, after = decode_activity_cursor(cursor)
        state: dict[str, Any] = {
            "draft_revision": 0 if draft is None else draft.revision,
            "company_revision": 0 if draft is None else draft.company_revision,
            "blockers": list(dict.fromkeys(blockers)),
            "candidates": [],
            "runs": [],
            "accounts": [],
            "versions": [],
            "next_cursor": None,
            "section": section,
        }
        for kind in ("candidates", "runs", "accounts", "versions"):
            rows = await self.repository.page(
                kind,
                agent_id,
                at if section == kind else None,
                after if section == kind else None,
                limit + 1,
            )
            if len(rows) > limit and section == kind:
                state["next_cursor"] = encode_activity_cursor(
                    rows[limit - 1]["created_at"],
                    rows[limit - 1]["version_id" if kind == "candidates" else "id"],
                )
            for item in rows[:limit]:
                if kind == "candidates":
                    version = await self.specs.get_version(item["version_id"])
                    if version is not None:
                        state[kind].append(
                            WorkspaceCandidateView(
                                version=version,
                                source=await self.sources.resolve(version.id),
                                created_at=item["created_at"],
                            )
                        )
                elif kind == "runs":
                    state[kind].append(
                        await WorkspacePublicationEvidenceService(
                            self.session, self.context, code_digest=self.code_digest
                        ).read(agent_id, item["id"])
                    )
                elif kind == "versions":
                    state[kind].append(await self.specs.get_version(item["id"]))
                else:
                    binding = await self.repository.binding_for_account(item["id"])
                    state[kind].append(
                        {
                            "id": item["id"],
                            "display_phone_number": item["display_phone_digits"],
                            "status": item["status"],
                            "health_status": item["health_status"],
                            "binding": binding,
                        }
                    )
        state["bindings"] = await self.repository.bindings_for_agent(agent_id)
        state["rollback_targets"] = [
            version.id
            for version in state["versions"]
            if version is not None
            and (
                version.configuration.code_digest == self.code_digest
                or self.compatible_versions.get(version.id)
                == version.configuration.code_digest
            )
            and await self.specs.original_deployment(version_id=version.id) is not None
        ]
        return WorkspacePublicationState.model_validate(state)
