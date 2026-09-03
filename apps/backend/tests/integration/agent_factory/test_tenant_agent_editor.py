from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.modules.agent_factory.repository import AgentSpecRepository
from agents_factory.modules.agent_factory.schemas import AgentPresentationUpdateRequest
from agents_factory.modules.agent_factory.service import AgentSpecLifecycleService
from agents_factory.modules.tenants.repository import TenantRepository


TENANT_ID = UUID("10000000-0000-0000-0000-000000000038")


@pytest.mark.asyncio
async def test_tenant_profile_and_agent_editor_are_resumable_and_version_safe(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants "
                "(id,slug,name,legal_name,industry,timezone,locale) VALUES "
                "(:id,'task38','Task 38','Task 38 SAS','Retail',"
                "'America/Bogota','es-CO')"
            ),
            {"id": TENANT_ID},
        )

    context = TenantContext(
        tenant_id=TENANT_ID,
        actor_id=uuid4(),
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        tenants = TenantRepository(session)
        await tenants.set_tenant_context(TENANT_ID)
        updated = await tenants.update_profile(
            tenant_id=TENANT_ID,
            expected_revision=1,
            name="Task 38 Store",
            legal_name="Task 38 SAS",
            industry="Commerce",
            timezone="America/Bogota",
            locale="en-US",
        )
        assert updated is not None
        assert (updated.name, updated.locale, updated.revision) == (
            "Task 38 Store",
            "en-US",
            2,
        )
        assert (
            await tenants.update_profile(
                tenant_id=TENANT_ID,
                expected_revision=1,
                name="Stale name",
                legal_name="Task 38 SAS",
                industry="Commerce",
                timezone="America/Bogota",
                locale="en-US",
            )
            is None
        )

        lifecycle = AgentSpecLifecycleService(
            repository=AgentSpecRepository(session, context)
        )
        assert await lifecycle.editor_state() is None
        instance, first = await lifecycle.create_customer_service_draft(
            business_name=updated.name
        )
        initial = await lifecycle.editor_state()
        assert initial is not None
        assert initial.editable_version.id == first.id
        assert initial.production_version is None

        second = await lifecycle.create_presentation_draft(
            agent_instance_id=instance.id,
            update=AgentPresentationUpdateRequest(
                expected_version_id=first.id,
                agent_name="Ana",
                tone="Cálido y empático",
                formality="Usted",
                brand_vocabulary=("Con gusto", "Estamos para ayudarle"),
                greeting="¡Hola! Soy Ana. ¿Cómo puedo ayudarle?",
                supported_locales=("en-US",),
                default_locale="en-US",
            ),
        )
        assert second.version_number == 2
        assert second.configuration.persona.agent_name == "Ana"
        assert second.configuration.language.supported_locales == ("en-US",)

        with pytest.raises(DomainError) as conflict:
            await lifecycle.create_presentation_draft(
                agent_instance_id=instance.id,
                update=AgentPresentationUpdateRequest(
                    expected_version_id=first.id,
                    greeting="This edit is stale",
                ),
            )
        assert conflict.value.code == "agent_spec_stale_write"

        resumed = await lifecycle.editor_state()
        assert resumed is not None
        assert resumed.editable_version.id == second.id
