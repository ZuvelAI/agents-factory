from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.modules.identity.methods import HashedChallengeMethod
from agents_factory.modules.identity.models import IdentityLevel, IdentityMethod
from agents_factory.modules.identity.repository import IdentityRepository
from agents_factory.modules.identity.service import IdentityService


NOW = datetime(2026, 8, 29, 14, tzinfo=UTC)
TENANT_A = UUID("10000000-0000-0000-0000-000000000214")
TENANT_B = UUID("20000000-0000-0000-0000-000000000214")


class Delivery:
    plaintext: str | None = None

    async def send(
        self,
        *,
        customer_ref: str,
        method: IdentityMethod,
        plaintext: str,
    ) -> None:
        _ = (customer_ref, method)
        self.plaintext = plaintext


def context(tenant_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=uuid4(),
    )


async def service(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    delivery: Delivery,
) -> IdentityService:
    await session.execute(text("SET LOCAL ROLE agents_factory_app"))
    operation_context = context(tenant_id)
    return IdentityService(
        context=operation_context,
        store=IdentityRepository(session, operation_context),
        challenge_method=HashedChallengeMethod(pepper=b"integration-pepper" * 2),
        delivery=delivery,
        max_attempts=2,
    )


@pytest.mark.asyncio
async def test_challenges_are_tenant_scoped_bounded_expiring_and_redacted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES "
                "(:tenant_a, 'identity-a', 'Identity A'), "
                "(:tenant_b, 'identity-b', 'Identity B')"
            ),
            {"tenant_a": TENANT_A, "tenant_b": TENANT_B},
        )

    delivery = Delivery()
    async with session_factory.begin() as session:
        identity_a = await service(session, tenant_id=TENANT_A, delivery=delivery)
        receipt = await identity_a.challenge(
            required_level=IdentityLevel.LEVEL_2,
            customer_ref="customer-a",
            method="ADDITIONAL_VERIFICATION",
            created_at=NOW,
        )
        assert delivery.plaintext is not None

    async with session_factory.begin() as session:
        identity_b = await service(session, tenant_id=TENANT_B, delivery=Delivery())
        with pytest.raises(DomainError) as foreign:
            await identity_b.verify(
                challenge_id=receipt.challenge_id,
                response=delivery.plaintext,
                verified_at=NOW + timedelta(seconds=1),
            )
        assert foreign.value.code == "identity_verification_failed"

    async with session_factory.begin() as session:
        identity_a = await service(session, tenant_id=TENANT_A, delivery=delivery)
        evidence = await identity_a.verify(
            challenge_id=receipt.challenge_id,
            response=delivery.plaintext,
            verified_at=NOW + timedelta(seconds=2),
        )
        assert evidence.achieved_level == 2

    async with session_factory.begin() as session:
        identity_a = await service(session, tenant_id=TENANT_A, delivery=Delivery())
        expired = await identity_a.challenge(
            required_level=IdentityLevel.LEVEL_2,
            customer_ref="customer-a",
            method="ADDITIONAL_VERIFICATION",
            created_at=NOW,
        )
        with pytest.raises(DomainError):
            await identity_a.verify(
                challenge_id=expired.challenge_id,
                response="000000",
                verified_at=NOW + timedelta(minutes=11),
            )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(TENANT_A)},
        )
        stored_digest = await session.scalar(
            text(
                "SELECT secret_digest FROM public.identity_challenges "
                "WHERE id = :challenge_id"
            ),
            {"challenge_id": receipt.challenge_id},
        )
        assert stored_digest != delivery.plaintext
        assert len(stored_digest) == 64
