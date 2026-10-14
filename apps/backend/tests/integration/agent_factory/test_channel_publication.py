from uuid import uuid4

import pytest
from sqlalchemy import text

from agents_factory.common.errors import DomainError


async def prepare_reviewed(session_factory, tenant, operation, revision=1):
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )
    from agents_factory.modules.agent_factory.publication_evidence import (
        PublicationEvidenceService,
    )
    from agents_factory.modules.agent_factory.publication_tests import (
        CandidateTestResult,
        ScenarioResult,
    )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        candidate = await PanelPublicationService(
            session, operation, code_digest="a" * 64
        ).prepare_candidate(expected_revision=revision)
        run = await PublicationEvidenceService(
            session, operation, code_digest="a" * 64
        ).request_tests(candidate.id)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await PublicationEvidenceService(
            session, operation, code_digest="a" * 64
        ).save_result(
            run.id,
            CandidateTestResult(
                scenarios=[
                    ScenarioResult(
                        key=key, prompt="Prueba", response="Respuesta", passed=True
                    )
                    for key in (
                        "greeting",
                        "known_fact",
                        "unknown_fact",
                        "scope",
                        "injection",
                        "human_control",
                    )
                ],
                checks_passed=True,
            ),
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await PublicationEvidenceService(
            session, operation, code_digest="a" * 64
        ).review(run.id, approved=True, expected_revision=revision)
    return candidate, run


async def account(session_factory, tenant, *, health="HEALTHY"):
    account_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts(id,tenant_id,provider,waba_id,phone_number_id,health_status) "
                "VALUES(:id,:tenant,'meta',:waba,:phone,:health)"
            ),
            {
                "id": account_id,
                "tenant": tenant,
                "waba": str(uuid4()),
                "phone": str(uuid4()),
                "health": health,
            },
        )
    return account_id


@pytest.mark.asyncio
async def test_account_publication_explicit_atomic_and_rollback_preserves_other_accounts(
    session_factory,
):
    from test_publication_candidates import configuration, context, seed
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )
    from agents_factory.modules.agent_factory.channel_binding import (
        AccountAgentBindingRepository,
    )

    tenant = await seed(session_factory, configuration())
    operation = context(tenant)
    first_account, second_account = (
        await account(session_factory, tenant),
        await account(session_factory, tenant),
    )
    first, run = await prepare_reviewed(session_factory, tenant, operation)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = PanelPublicationService(session, operation, code_digest="a" * 64)
        binding = await service.publish(
            version_id=first.id,
            whatsapp_account_id=first_account,
            expected_revision=1,
            test_run_id=run.id,
            expected_binding_revision=0,
        )
        assert binding.version_id == first.id and binding.revision == 1
        from agents_factory.modules.tenants.onboarding import OnboardingService

        wizard = await OnboardingService(
            session, operation, code_digest="a" * 64
        ).read()
        assert (
            next(step for step in wizard.steps if step.key == "quality-gate").status
            == "COMPLETE"
        )
        assert (
            next(step for step in wizard.steps if step.key == "production").status
            == "COMPLETE"
        )
        await service.publish(
            version_id=first.id,
            whatsapp_account_id=second_account,
            expected_revision=1,
            test_run_id=run.id,
            expected_binding_revision=0,
        )
        await session.execute(
            text(
                "UPDATE public.tenant_onboarding_configs SET revision=2 WHERE tenant_id=:tenant"
            ),
            {"tenant": tenant},
        )
    second, run2 = await prepare_reviewed(session_factory, tenant, operation, 2)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = PanelPublicationService(session, operation, code_digest="a" * 64)
        updated = await service.publish(
            version_id=second.id,
            whatsapp_account_id=first_account,
            expected_revision=2,
            test_run_id=run2.id,
            expected_binding_revision=1,
        )
        assert updated.revision == 2
        for revision in range(3, 24):
            await session.execute(
                text(
                    "UPDATE public.tenant_onboarding_configs SET revision=:revision WHERE tenant_id=:tenant"
                ),
                {"revision": revision, "tenant": tenant},
            )
            await service.prepare_candidate(expected_revision=revision)
        state = await service.read_state()
        assert first.id not in [v.id for v in state.candidates]
        assert first.id in [
            v.id
            for v in state.rollback_targets
            if v.whatsapp_account_id == first_account
        ]
        from agents_factory.modules.agent_factory.repository import (
            ProductionAgentSpecProvider,
        )

        pinned = await ProductionAgentSpecProvider(
            session, agent_instance_id=first.agent_instance_id, version_id=first.id
        ).get_active(tenant_id=tenant)
        assert pinned.id == first.id
        repository = AccountAgentBindingRepository(session, operation)
        assert (await repository.get_for_account(second_account)).version_id == first.id
        with pytest.raises(DomainError):
            await service.rollback(
                whatsapp_account_id=first_account,
                target_version_id=first.id,
                expected_binding_revision=1,
            )
        reverted = await service.rollback(
            whatsapp_account_id=first_account,
            target_version_id=first.id,
            expected_binding_revision=2,
        )
        assert reverted.version_id == first.id and reverted.revision == 3
        assert (await repository.get_for_account(second_account)).version_id == first.id
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.account_agent_binding_history WHERE tenant_id=:tenant"
                ),
                {"tenant": tenant},
            )
            == 4
        )


@pytest.mark.asyncio
async def test_publish_rejects_unhealthy_wrong_tenant_and_unreviewed_candidate(
    session_factory,
):
    from test_publication_candidates import configuration, context, seed
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )

    tenant = await seed(session_factory, configuration())
    other = await seed(session_factory, configuration())
    operation = context(tenant)
    bad, foreign = (
        await account(session_factory, tenant, health="UNKNOWN"),
        await account(session_factory, other),
    )
    candidate, run = await prepare_reviewed(session_factory, tenant, operation)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = PanelPublicationService(session, operation, code_digest="a" * 64)
        for selected in (bad, foreign):
            with pytest.raises(DomainError):
                await service.publish(
                    version_id=candidate.id,
                    whatsapp_account_id=selected,
                    expected_revision=1,
                    test_run_id=run.id,
                    expected_binding_revision=0,
                )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.account_agent_bindings")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_publish_without_review_or_with_stale_revision_leaves_agent_unpublished(
    session_factory,
):
    from test_publication_candidates import configuration, context, seed
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )
    from agents_factory.modules.agent_factory.publication_evidence import (
        PublicationEvidenceService,
    )

    tenant = await seed(session_factory, configuration())
    operation = context(tenant)
    selected = await account(session_factory, tenant)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = PanelPublicationService(session, operation, code_digest="a" * 64)
        version = await service.prepare_candidate(expected_revision=1)
        run = await PublicationEvidenceService(
            session, operation, code_digest="a" * 64
        ).request_tests(version.id)
        for revision in (1, 2):
            with pytest.raises(DomainError):
                await service.publish(
                    version_id=version.id,
                    whatsapp_account_id=selected,
                    expected_revision=revision,
                    test_run_id=run.id,
                    expected_binding_revision=0,
                )
        assert (
            await session.scalar(
                text("SELECT state FROM public.agent_spec_versions WHERE id=:id"),
                {"id": version.id},
            )
            == "TEST"
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.account_agent_bindings")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_concurrent_same_candidate_publish_increments_binding_once(
    session_factory,
):
    import asyncio
    from test_publication_candidates import configuration, context, seed
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )

    tenant = await seed(session_factory, configuration())
    operation = context(tenant)
    selected = await account(session_factory, tenant)
    version, run = await prepare_reviewed(session_factory, tenant, operation)

    async def publish_once():
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            return await PanelPublicationService(
                session, operation, code_digest="a" * 64
            ).publish(
                version_id=version.id,
                whatsapp_account_id=selected,
                expected_revision=1,
                test_run_id=run.id,
                expected_binding_revision=0,
            )

    results = await asyncio.gather(publish_once(), publish_once())
    assert [r.revision for r in results] == [1, 1]
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.account_agent_binding_history")
            )
            == 1
        )
