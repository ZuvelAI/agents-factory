from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.modules.whatsapp.account_service import WhatsAppAccountRepository
from agents_factory.modules.whatsapp.contracts import WhatsAppMode


class StateBinding(TypedDict):
    state_digest: str
    tenant_id: UUID
    admin_user_id: UUID
    admin_session_id: UUID
    requested_mode: WhatsAppMode


async def seed_state(
    session_factory: async_sessionmaker[AsyncSession],
    mode: WhatsAppMode,
) -> tuple[StateBinding, datetime]:
    now = datetime.now(UTC)
    values: StateBinding = {
        "state_digest": uuid4().hex + uuid4().hex,
        "tenant_id": uuid4(),
        "admin_user_id": uuid4(),
        "admin_session_id": uuid4(),
        "requested_mode": mode,
    }
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES (:id, :slug, 'Test')"
            ),
            {"id": values["tenant_id"], "slug": str(values["tenant_id"])},
        )
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await WhatsAppAccountRepository(session).save_signup_state(
            **values,
            expires_at=now + timedelta(minutes=10),
        )
    return values, now


async def consume(
    session_factory: async_sessionmaker[AsyncSession],
    values: StateBinding,
    now: datetime,
) -> bool:
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        return await WhatsAppAccountRepository(session).consume_signup_state(
            **values,
            consumed_at=now,
        )


@pytest.mark.parametrize("mode", ["API_ONLY", "COEXISTENCE"])
@pytest.mark.parametrize(
    "binding",
    ["requested_mode", "tenant_id", "admin_user_id", "admin_session_id"],
)
async def test_signup_state_rejects_changed_binding_without_consuming(
    session_factory: async_sessionmaker[AsyncSession],
    mode: WhatsAppMode,
    binding: str,
) -> None:
    values, now = await seed_state(session_factory, mode)
    changed = values.copy()
    if binding == "requested_mode":
        changed["requested_mode"] = "COEXISTENCE" if mode == "API_ONLY" else "API_ONLY"
    elif binding == "tenant_id":
        changed["tenant_id"] = uuid4()
    elif binding == "admin_user_id":
        changed["admin_user_id"] = uuid4()
    else:
        changed["admin_session_id"] = uuid4()

    assert not await consume(session_factory, changed, now)
    assert await consume(session_factory, values, now)
    assert not await consume(session_factory, values, now)


async def test_signup_state_expires_at_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    values, now = await seed_state(session_factory, "COEXISTENCE")
    assert not await consume(session_factory, values, now + timedelta(minutes=10))


async def test_concurrent_signup_callbacks_only_consume_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    values, now = await seed_state(session_factory, "COEXISTENCE")
    results = await asyncio.gather(
        consume(session_factory, values, now),
        consume(session_factory, values, now),
    )
    assert sorted(results) == [False, True]


async def test_provider_rollback_does_not_restore_consumed_signup_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    values, now = await seed_state(session_factory, "COEXISTENCE")
    async with session_factory() as session:
        await session.begin()
        repository = WhatsAppAccountRepository(
            session,
            state_session_factory=session_factory,
        )
        assert await repository.consume_signup_state(**values, consumed_at=now)
        await session.rollback()
    assert not await consume(session_factory, values, now)
