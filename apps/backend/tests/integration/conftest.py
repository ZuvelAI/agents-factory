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


async def _truncate_foundation_tables(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "ALTER TABLE public.audit_events "
            "DISABLE TRIGGER audit_events_reject_truncate"
        )
    )
    await connection.execute(
        text(
            "ALTER TABLE public.agent_spec_deployments "
            "DISABLE TRIGGER agent_spec_deployments_append_only"
        )
    )
    await connection.execute(
        text(
            "ALTER TABLE public.action_events DISABLE TRIGGER action_events_append_only"
        )
    )
    for table_name, trigger_name in (
        ("approval_decisions", "approval_decisions_append_only"),
        ("case_events", "case_events_append_only"),
        ("case_operations", "case_operations_append_only"),
        ("knowledge_source_versions", "knowledge_source_versions_append_only"),
        ("structured_facts", "structured_facts_append_only"),
        ("knowledge_documents", "knowledge_documents_append_only"),
        ("knowledge_version_members", "knowledge_version_members_append_only"),
        (
            "knowledge_ingestion_artifacts",
            "knowledge_ingestion_artifacts_append_only",
        ),
        ("knowledge_chunks", "knowledge_chunks_append_only"),
    ):
        await connection.execute(
            text(f"ALTER TABLE public.{table_name} DISABLE TRIGGER {trigger_name}")
        )
    await connection.execute(
        text(
            "TRUNCATE TABLE "
            "public.knowledge_chunks, "
            "public.knowledge_ingestion_artifacts, "
            "public.knowledge_ingestions, "
            "public.knowledge_version_members, "
            "public.knowledge_versions, "
            "public.knowledge_documents, "
            "public.structured_facts, "
            "public.knowledge_source_versions, "
            "public.knowledge_sources, "
            "public.action_events, "
            "public.actions, "
            "public.identity_evidence, "
            "public.identity_challenges, "
            "public.identity_subjects, "
            "public.agent_spec_deployments, "
            "public.agent_spec_versions, "
            "public.agent_instances, "
            "public.outbound_messages, "
            "public.whatsapp_templates, "
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
            "ALTER TABLE public.action_events ENABLE TRIGGER action_events_append_only"
        )
    )
    for table_name, trigger_name in (
        ("approval_decisions", "approval_decisions_append_only"),
        ("case_events", "case_events_append_only"),
        ("case_operations", "case_operations_append_only"),
        ("knowledge_source_versions", "knowledge_source_versions_append_only"),
        ("structured_facts", "structured_facts_append_only"),
        ("knowledge_documents", "knowledge_documents_append_only"),
        ("knowledge_version_members", "knowledge_version_members_append_only"),
        (
            "knowledge_ingestion_artifacts",
            "knowledge_ingestion_artifacts_append_only",
        ),
        ("knowledge_chunks", "knowledge_chunks_append_only"),
    ):
        await connection.execute(
            text(f"ALTER TABLE public.{table_name} ENABLE TRIGGER {trigger_name}")
        )
    await connection.execute(
        text(
            "ALTER TABLE public.agent_spec_deployments "
            "ENABLE TRIGGER agent_spec_deployments_append_only"
        )
    )
    await connection.execute(
        text(
            "ALTER TABLE public.audit_events "
            "ENABLE TRIGGER audit_events_reject_truncate"
        )
    )


@pytest.fixture(scope="session")
def local_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail(
            "TEST_DATABASE_URL is required; run integration tests through "
            "`make test-integration`"
        )

    parsed = urlsplit(database_url)
    if parsed.scheme != "postgresql+asyncpg" or parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        pytest.fail("integration tests require the isolated local Supabase database")
    return database_url


@pytest_asyncio.fixture
async def database_engine(local_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(local_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(
    database_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(database_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_foundation_tables(database_engine: AsyncEngine) -> AsyncIterator[None]:
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "GRANT agents_factory_app, agents_factory_admin TO CURRENT_USER "
                "WITH INHERIT FALSE, SET TRUE"
            )
        )
        await _truncate_foundation_tables(connection)
    yield
    async with database_engine.begin() as connection:
        await _truncate_foundation_tables(connection)
        await connection.execute(
            text(
                "GRANT agents_factory_app, agents_factory_admin TO CURRENT_USER "
                "WITH INHERIT FALSE, SET FALSE"
            )
        )
