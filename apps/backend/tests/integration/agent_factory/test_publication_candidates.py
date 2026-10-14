from collections.abc import AsyncIterator
from uuid import uuid4
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.security import (
    AdminPrincipal,
    PlatformAdminAuthorizer,
    require_platform_admin,
)
from agents_factory.dependencies import TransactionSession, get_transaction
from agents_factory.main import create_app
from agents_factory.modules.tenants.onboarding import OnboardingConfiguration


def configuration():
    return OnboardingConfiguration.model_validate(
        {
            "company": {
                "legal_name": "Zuvel",
                "commercial_name": "Zuvel",
                "country": "Colombia",
                "city": "Bogotá",
                "industry": "Servicios",
                "business_description": "Servicios digitales",
                "service_hours": "9 a 5",
                "responsible_person": "Daniel",
                "privacy_contact": "admin@example.com",
                "incident_contact": "admin@example.com",
            },
            "agent": {
                "greeting": "Bienvenido a Zuvel",
                "instructions": "Orienta sobre servicios",
                "supported_languages": ["es-CO"],
            },
            "capabilities": {"use_cases": ["company_information"]},
            "integrations": {"business_systems_required": False},
            "knowledge": {
                "source_name": "Manual",
                "source_type": "INTERNAL_TEXT",
                "source_reference": "Manual aprobado",
                "approved_summary": "Ofrecemos servicios digitales",
                "review_confirmed": True,
            },
            "policies_identity": {
                "pricing_response": "QUOTE_REQUIRED",
                "privacy_policy_status": "APPROVED",
                "customer_identity_method": "NONE",
            },
            "human_operations": {"handoff_enabled": False},
            "approval_routes": {"high_risk_actions_expected": False},
        }
    )


async def seed(session_factory, config):
    tenant = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text("INSERT INTO public.tenants(id,slug,name) VALUES(:id,:slug,'Zuvel')"),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.tenant_onboarding_configs(tenant_id,revision,configuration) VALUES(:id,1,:config)"
            ).bindparams(bindparam("config", type_=JSONB)),
            {"id": tenant, "config": config.model_dump(mode="json")},
        )
    return tenant


def context(tenant):
    return TenantContext(
        tenant_id=tenant,
        actor_id=uuid4(),
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_prepare_candidate_preserves_saved_config_and_reuses_revision(
    session_factory,
):
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )

    config = configuration()
    tenant = await seed(session_factory, config)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = PanelPublicationService(
            session, context(tenant), code_digest="a" * 64
        )
        first = await service.prepare_candidate(expected_revision=1)
        same = await service.prepare_candidate(expected_revision=1)
        assert first.id == same.id and first.state == "TEST"
        saved = await session.scalar(
            text(
                "SELECT configuration FROM public.tenant_onboarding_configs WHERE tenant_id=:id"
            ),
            {"id": tenant},
        )
        assert saved == config.model_dump(mode="json")
        with pytest.raises(DomainError) as error:
            await service.prepare_candidate(expected_revision=2)
        assert error.value.status == 409
        state = await service.read_state()
        assert state.saved_revision == 1
        assert state.candidates[0].id == first.id
        assert state.accounts == []
        from agents_factory.modules.agent_factory.publication_evidence import (
            PublicationEvidenceService,
        )

        run = await PublicationEvidenceService(
            session, context(tenant), code_digest="a" * 64
        ).request_tests(first.id)
        reopened = await service.read_state()
        assert reopened.test_runs[0].id == run.id
        assert reopened.test_runs[0].version_id == first.id
        from agents_factory.modules.tenants.onboarding import OnboardingService

        wizard = await OnboardingService(session, context(tenant)).read()
        assert (
            next(step for step in wizard.steps if step.key == "knowledge").status
            == "COMPLETE"
        )


@pytest.mark.asyncio
async def test_candidate_missing_configuration_or_build_provenance_is_blocked(
    session_factory,
):
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )

    tenant = await seed(session_factory, OnboardingConfiguration())
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = PanelPublicationService(session, context(tenant), code_digest=None)
        state = await service.read_state()
        assert state.blockers
        with pytest.raises(DomainError) as error:
            await service.prepare_candidate(expected_revision=1)
        assert error.value.status == 409


@pytest.mark.asyncio
async def test_publication_routes_require_admin_and_existing_tenant(session_factory):
    app = create_app()

    class Verifier:
        async def verify(self, access_jwt):
            return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    app.state.platform_admin_authorizer = PlatformAdminAuthorizer(Verifier())
    app.state.settings = SimpleNamespace(agent_publication_code_digest=None)

    async def transaction() -> AsyncIterator:
        async with session_factory.begin() as session:
            yield session

    app.dependency_overrides[get_transaction] = transaction
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/admin/tenants/{uuid4()}/agent-publication")
        assert response.status_code == 401

    async def admin(session: TransactionSession) -> AdminPrincipal:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    app.dependency_overrides[require_platform_admin] = admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/admin/tenants/{uuid4()}/agent-publication")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_unsupported_identity_is_visible_before_preparation(session_factory):
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )

    config = configuration()
    config = config.model_copy(
        update={
            "policies_identity": config.policies_identity.model_copy(
                update={"customer_identity_method": "ONE_TIME_CODE"}
            )
        }
    )
    tenant = await seed(session_factory, config)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        state = await PanelPublicationService(
            session, context(tenant), code_digest="a" * 64
        ).read_state()
        assert any("identidad" in blocker for blocker in state.blockers)
