from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agents_factory.common.errors import DomainError
from agents_factory.common.security import AdminPrincipal
from agents_factory.main import create_app
from agents_factory.modules.tenants import admin_router
from agents_factory.modules.tenants.admin_router import TenantCreateRequest
from agents_factory.modules.tenants.models import Tenant


class FakeTenantService:
    created_with: dict[str, object] | None = None

    def __init__(self, session: object) -> None:
        self.session = session

    async def create_tenant(self, **values: object) -> Tenant:
        self.created_with = values
        now = datetime.now(UTC)
        return Tenant(
            id=uuid4(),
            slug=str(values["slug"]),
            name=str(values["name"]),
            status="active",
            created_at=now,
            updated_at=now,
        )


class FakeTenantRepository:
    tenant: Tenant | None = None

    def __init__(self, session: object) -> None:
        self.session = session

    async def get(self, tenant_id: object) -> Tenant | None:
        return self.tenant


@pytest.mark.asyncio
async def test_admin_create_tenant_reuses_atomic_service_and_request_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_service = FakeTenantService(None)
    monkeypatch.setattr(admin_router, "TenantService", lambda _: fake_service)
    correlation_id = uuid4()
    principal = AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    response = await admin_router.create_admin_tenant(
        payload=TenantCreateRequest(slug="acme", name="Acme"),
        request=SimpleNamespace(state=SimpleNamespace(correlation_id=correlation_id)),
        principal=principal,
        session=object(),
        idempotency_key="tenant:create:acme",
    )

    assert response.slug == "acme"
    assert fake_service.created_with == {
        "slug": "acme",
        "name": "Acme",
        "actor_id": principal.user_id,
        "actor_type": "platform_admin",
        "correlation_id": correlation_id,
        "idempotency_key": "tenant:create:acme",
    }


@pytest.mark.asyncio
async def test_admin_read_tenant_returns_only_repository_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    tenant = Tenant(
        id=tenant_id,
        slug="acme",
        name="Acme",
        status="active",
        created_at=now,
        updated_at=now,
    )
    repository = FakeTenantRepository(None)
    repository.tenant = tenant
    monkeypatch.setattr(admin_router, "TenantRepository", lambda _: repository)

    response = await admin_router.read_admin_tenant(
        tenant_id=tenant_id,
        principal=AdminPrincipal(user_id=uuid4(), session_id=uuid4()),
        session=object(),
    )

    assert response.id == tenant_id
    assert response.name == "Acme"


@pytest.mark.asyncio
async def test_admin_read_tenant_uses_stable_not_found_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeTenantRepository(None)
    monkeypatch.setattr(admin_router, "TenantRepository", lambda _: repository)

    with pytest.raises(DomainError) as caught:
        await admin_router.read_admin_tenant(
            tenant_id=uuid4(),
            principal=AdminPrincipal(user_id=uuid4(), session_id=uuid4()),
            session=object(),
        )

    assert caught.value.status == 404
    assert caught.value.code == "tenant_not_found"


def test_private_admin_tenant_routes_are_mounted_by_the_app_factory() -> None:
    route_paths = {route.path for route in create_app().routes}

    assert "/admin/tenants" in route_paths
    assert "/admin/tenants/{tenant_id}" in route_paths
