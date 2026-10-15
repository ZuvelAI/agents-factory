"""Explicit, one-instance import. Legacy configuration remains unchanged."""

from uuid import UUID

from agents_factory.modules.tenants.onboarding import OnboardingConfiguration
from .compiler import canonical_json
from .configuration_models import AgentEditableConfiguration, DraftView
from .configuration_service import AgentConfigurationService
from .publication_service import publication_problem


class LegacyConfigurationImportService(AgentConfigurationService):
    async def import_draft(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        expected_legacy_revision: int,
        expected_company_revision: int,
    ) -> DraftView:
        repository = await self.scope(tenant_id, agent_id)
        source = await repository.lock_legacy()
        if source is None or source["revision"] != expected_legacy_revision:
            self.conflict()
        assert source is not None
        if await repository.legacy_instance(expected_legacy_revision) != agent_id:
            raise publication_problem(
                "legacy_agent_ambiguous",
                "No existe una asociación inequívoca con esta instancia. No se importó nada.",
                409,
            )
        legacy = OnboardingConfiguration.model_validate(source["configuration"])
        provenance = {
            "source": "legacy_onboarding",
            "legacy_revision": expected_legacy_revision,
            "source_digest": canonical_json(legacy).digest,
        }
        profile = await repository.lock_company()
        existing = await repository.read_draft(agent_id)
        if existing is not None:
            if (
                existing["revision"] == 1
                and existing["provenance"] == provenance
                and profile is not None
            ):
                return self.draft_view(existing, profile)
            self.conflict()
        if profile is None:
            if expected_company_revision != 0 or not legacy.company.commercial_name:
                self.conflict()
            profile = await repository.insert_company(
                legacy.company.model_dump(mode="json")
            )
            if profile is None:
                self.conflict()
            assert profile is not None
            await repository.update_company_name(legacy.company.commercial_name)
        elif profile["revision"] != expected_company_revision or profile[
            "configuration"
        ] != legacy.company.model_dump(mode="json"):
            self.conflict()
        config = AgentEditableConfiguration.model_validate(
            legacy.model_dump(mode="json", exclude={"company"})
        )
        row = await repository.insert_draft(
            agent_id=agent_id,
            company_revision=profile["revision"],
            company_snapshot=profile["configuration"],
            configuration=config.model_dump(mode="json"),
            provenance=provenance,
        )
        if row is None:
            self.conflict()
        assert row is not None
        await self.audit(
            tenant_id,
            agent_id,
            "agent.legacy_configuration_imported",
            1,
            ["legacy_configuration"],
        )
        return self.draft_view(row, profile)
