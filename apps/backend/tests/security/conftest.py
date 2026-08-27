from __future__ import annotations

import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


async def _truncate_conversation_tables(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "ALTER TABLE public.audit_events "
            "DISABLE TRIGGER audit_events_reject_truncate"
        )
    )
    await connection.execute(
        text(
            "TRUNCATE TABLE "
            "public.conversation_state_events, "
            "public.messages, "
            "public.conversations, "
            "public.whatsapp_webhook_events, "
            "public.whatsapp_accounts, "
            "public.dead_letter_jobs, "
            "public.job_attempts, "
            "public.outbox_jobs, "
            "public.audit_events, "
            "public.platform_admins, "
            "public.tenants CASCADE"
        )
    )
    await connection.execute(
        text(
            "ALTER TABLE public.audit_events "
            "ENABLE TRIGGER audit_events_reject_truncate"
        )
    )


@pytest.fixture(scope="session")
def conversation_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail("TEST_DATABASE_URL is required for conversation security tests")
    parsed = urlsplit(database_url)
    if parsed.scheme != "postgresql+asyncpg" or parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        pytest.fail("conversation security tests require local Supabase")
    return database_url


@pytest_asyncio.fixture
async def conversation_database_engine(
    conversation_database_url: str,
) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(conversation_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def conversation_session_factory(
    conversation_database_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(conversation_database_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def clean_conversation_tables(
    conversation_database_engine: AsyncEngine,
) -> AsyncIterator[None]:
    async with conversation_database_engine.begin() as connection:
        await connection.execute(
            text(
                "GRANT agents_factory_app, agents_factory_admin TO CURRENT_USER "
                "WITH INHERIT FALSE, SET TRUE"
            )
        )
        await _truncate_conversation_tables(connection)
    yield
    async with conversation_database_engine.begin() as connection:
        await _truncate_conversation_tables(connection)
        await connection.execute(
            text(
                "GRANT agents_factory_app, agents_factory_admin TO CURRENT_USER "
                "WITH INHERIT FALSE, SET FALSE"
            )
        )
