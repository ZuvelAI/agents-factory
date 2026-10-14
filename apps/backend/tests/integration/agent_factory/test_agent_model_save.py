from sqlalchemy import text

from apps.backend.tests.integration.agent_factory.test_publication_candidates import (
    configuration,
    context,
    seed,
)
from agents_factory.modules.tenants.onboarding import (
    OnboardingRepository,
    OnboardingService,
    UpdateOnboardingStepRequest,
)


async def test_panel_agent_edit_preserves_selected_model_when_field_is_omitted(
    session_factory,
):
    config = configuration()
    tenant = await seed(session_factory, config)
    operation = context(tenant)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = OnboardingService(session, operation, code_digest="a" * 64)
        data = {**config.agent.model_dump(mode="json"), "model": "gpt-6-luna"}
        await service.update(
            step="agent",
            request=UpdateOnboardingStepRequest(expected_revision=1, data=data),
        )
        data.pop("model")
        data["greeting"] = "Nuevo saludo de Zuvel"
        await service.update(
            step="agent",
            request=UpdateOnboardingStepRequest(expected_revision=2, data=data),
        )
        stored = await OnboardingRepository(session, operation).read()
        assert stored.revision == 3
        assert stored.configuration.agent.model == "gpt-6-luna"
        assert stored.configuration.agent.greeting == "Nuevo saludo de Zuvel"
        data["model"] = "gpt-5.6-luna"
        await service.update(
            step="agent",
            request=UpdateOnboardingStepRequest(expected_revision=3, data=data),
        )
        assert (
            await OnboardingRepository(session, operation).read()
        ).configuration.agent.model == "gpt-5.6-luna"
