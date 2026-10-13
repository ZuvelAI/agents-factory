from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agents_factory.common.context import TenantContext
from agents_factory.modules.tenants.onboarding import KnowledgeConfiguration


def approved(**changes):
    values = dict(
        source_name="Zuvel",
        source_type="INTERNAL_TEXT",
        source_reference="Manual revisado",
        authority="OFFICIAL",
        approved_summary="Zuvel ofrece atención empresarial.",
        review_confirmed=True,
    )
    return KnowledgeConfiguration(**(values | changes))


def context(tenant_id):
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=uuid4(),
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )


async def seed(session_factory):
    tenant_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name) VALUES(:id,:slug,'Knowledge')"
            ),
            {"id": tenant_id, "slug": str(tenant_id)},
        )
    return tenant_id


@pytest.mark.asyncio
async def test_freeze_idempotent_and_changes_version_content(session_factory):
    from agents_factory.modules.agent_factory.approved_knowledge import (
        ApprovedKnowledgeRepository,
    )

    tenant = await seed(session_factory)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        repo = ApprovedKnowledgeRepository(session, context(tenant))
        first = await repo.freeze(approved())
        same = await repo.freeze(approved())
        assert first.id == same.id
        assert len(first.digest) == 64
        assert first.approved_summary == "Zuvel ofrece atención empresarial."
        for changes in (
            {"approved_summary": "Otro contenido"},
            {"source_reference": "Referencia nueva"},
            {"authority": "REFERENCE"},
        ):
            other = await repo.freeze(approved(**changes))
            assert other.id != first.id
            assert other.digest != first.digest
        assert await repo.get_by_digest(first.digest) == first


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"approved_summary": ""},
        {"approved_summary": "  "},
        {"review_confirmed": False},
        {"critical_conflicts": 1},
        {"source_name": ""},
        {"source_reference": ""},
        {
            "source_type": "WEBSITE",
            "source_reference": "https://example.com",
            "approved_summary": "",
        },
    ],
)
async def test_freeze_rejects_unapproved_or_missing_content(session_factory, changes):
    from agents_factory.modules.agent_factory.approved_knowledge import (
        ApprovedKnowledgeRepository,
    )

    tenant = await seed(session_factory)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        repo = ApprovedKnowledgeRepository(session, context(tenant))
        with pytest.raises(ValueError, match="approved knowledge"):
            await repo.freeze(approved(**changes))
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.agent_approved_knowledge_versions")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_knowledge_read_is_tenant_scoped_even_for_admin(session_factory):
    from agents_factory.modules.agent_factory.approved_knowledge import (
        ApprovedKnowledgeRepository,
    )

    first_tenant, second_tenant = (
        await seed(session_factory),
        await seed(session_factory),
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        first = await ApprovedKnowledgeRepository(
            session, context(first_tenant)
        ).freeze(approved())
        assert (
            await ApprovedKnowledgeRepository(
                session, context(second_tenant)
            ).get_by_digest(first.digest)
            is None
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.agent_approved_knowledge_versions")
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["agents_factory_app", "agents_factory_admin"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
async def test_knowledge_cannot_be_changed_by_runtime_or_admin(
    session_factory, role, operation
):
    from agents_factory.modules.agent_factory.approved_knowledge import (
        ApprovedKnowledgeRepository,
    )

    tenant = await seed(session_factory)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        item = await ApprovedKnowledgeRepository(session, context(tenant)).freeze(
            approved()
        )
    async with session_factory.begin() as session:
        roles = {
            "agents_factory_app": "SET LOCAL ROLE agents_factory_app",
            "agents_factory_admin": "SET LOCAL ROLE agents_factory_admin",
        }
        await session.execute(text(roles[role]))
        await session.execute(
            text("SELECT set_config('app.tenant_id',:id,true)"), {"id": str(tenant)}
        )
        statement = (
            "UPDATE public.agent_approved_knowledge_versions SET digest=repeat('a',64) WHERE id=:id"
            if operation == "UPDATE"
            else "DELETE FROM public.agent_approved_knowledge_versions WHERE id=:id"
        )
        with pytest.raises(DBAPIError):
            await session.execute(text(statement), {"id": item.id})
