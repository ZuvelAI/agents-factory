from __future__ import annotations

import os
import re
import sys
import tomllib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agents_factory.common.errors import DomainError
from agents_factory.common.security import AdminPrincipal, PlatformAdminAuthorizer
from agents_factory.modules.tenants.repository import TenantRepository


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT / "infrastructure/scripts"))

from local_database_url import (  # noqa: E402
    LocalDatabaseUrlError,
    validate_test_database_url,
)


MISSING_CONTEXT: Final = object()
RESET_CONTEXT: Final = object()
EXPECTED_DATABASE: Final = "postgres"
UUID_PATTERN: Final = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


@dataclass(frozen=True, slots=True)
class TenantIsolationRegistration:
    table_name: str
    owner_column: str = "tenant_id"
    insert_allowed: bool = True
    update_allowed: bool = True
    delete_allowed: bool = False
    reassignment_denials: frozenset[str] = frozenset({"42501"})


TENANT_ISOLATION_REGISTRY = (
    TenantIsolationRegistration(
        "public.cases", insert_allowed=False, update_allowed=False
    ),
    TenantIsolationRegistration(
        "public.case_events", insert_allowed=False, update_allowed=False
    ),
    TenantIsolationRegistration(
        "public.case_operations", insert_allowed=False, update_allowed=False
    ),
    TenantIsolationRegistration(
        "public.case_delivery_operations", insert_allowed=False, update_allowed=False
    ),
    TenantIsolationRegistration(
        "public.media_observations", insert_allowed=False, update_allowed=False
    ),
    TenantIsolationRegistration(
        "public.media_evidence", insert_allowed=False, update_allowed=False
    ),
    TenantIsolationRegistration(
        "public.order_operations", insert_allowed=False, update_allowed=False
    ),
    TenantIsolationRegistration(
        "public.appointment_configurations", insert_allowed=False, update_allowed=False
    ),
    TenantIsolationRegistration(
        "public.appointments", insert_allowed=False, update_allowed=False
    ),
    TenantIsolationRegistration(
        "public.appointment_operations", insert_allowed=False, update_allowed=False
    ),
    TenantIsolationRegistration(
        "public.integration_connections",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.tenants",
        "id",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.audit_events",
        insert_allowed=True,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration("public.outbox_jobs", delete_allowed=False),
    TenantIsolationRegistration("public.job_attempts", delete_allowed=False),
    TenantIsolationRegistration("public.dead_letter_jobs", delete_allowed=False),
    TenantIsolationRegistration(
        "public.secret_envelopes",
        insert_allowed=True,
        update_allowed=False,
        delete_allowed=True,
    ),
    TenantIsolationRegistration(
        "public.whatsapp_accounts",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.whatsapp_webhook_events",
        insert_allowed=True,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration("public.whatsapp_templates", delete_allowed=False),
    TenantIsolationRegistration("public.conversations", delete_allowed=False),
    TenantIsolationRegistration(
        "public.messages",
        insert_allowed=True,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.conversation_state_events",
        insert_allowed=True,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration("public.outbound_messages", delete_allowed=False),
    TenantIsolationRegistration(
        "public.agent_instances",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.agent_spec_versions",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.agent_spec_deployments",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration("public.identity_subjects", delete_allowed=False),
    TenantIsolationRegistration("public.identity_challenges", delete_allowed=False),
    TenantIsolationRegistration(
        "public.identity_evidence",
        delete_allowed=False,
        reassignment_denials=frozenset({"42501", "55000"}),
    ),
    TenantIsolationRegistration(
        "public.actions",
        delete_allowed=False,
        reassignment_denials=frozenset({"42501", "55000"}),
    ),
    TenantIsolationRegistration(
        "public.action_events",
        insert_allowed=True,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_sources",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_source_versions",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.structured_facts",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_documents",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_versions",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_version_members",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_ingestions",
        insert_allowed=False,
        update_allowed=True,
        delete_allowed=False,
        reassignment_denials=frozenset({"42501", "55000"}),
    ),
    TenantIsolationRegistration(
        "public.knowledge_ingestion_artifacts",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_chunks",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_proposals",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_conflicts",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_source_diffs",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.knowledge_eval_evidence",
        insert_allowed=False,
        update_allowed=False,
        delete_allowed=False,
    ),
)


@dataclass(frozen=True, slots=True)
class DenialFingerprint:
    exception_type: str
    sqlstate: str
    message: str
    detail: str | None
    schema_name: str | None
    table_name: str | None
    constraint_name: str | None


@dataclass(frozen=True, slots=True)
class SeededWorld:
    tenant_a: UUID
    tenant_b: UUID
    row_a: dict[str, UUID]
    row_b: dict[str, UUID]
    insert_parent_a: UUID
    insert_parent_b: UUID
    whatsapp_account_a: UUID
    whatsapp_account_b: UUID


@pytest.fixture(scope="session")
def local_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail("TEST_DATABASE_URL must be supplied by the local matrix runner")
    if (REPOSITORY_ROOT / "supabase/.temp/project-ref").exists():
        pytest.fail("linked Supabase projects are forbidden for tenant isolation tests")
    try:
        with (REPOSITORY_ROOT / "supabase/config.toml").open("rb") as config_file:
            expected_port = tomllib.load(config_file)["db"]["port"]
        if not isinstance(expected_port, int):
            raise TypeError
        return validate_test_database_url(
            database_url,
            expected_port=expected_port,
            expected_database=EXPECTED_DATABASE,
        )
    except (
        KeyError,
        LocalDatabaseUrlError,
        OSError,
        TypeError,
        tomllib.TOMLDecodeError,
    ):
        pytest.fail(
            "tenant isolation tests require canonical local Supabase PostgreSQL"
        )


@pytest_asyncio.fixture
async def database_engine(local_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(local_database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "GRANT agents_factory_app, agents_factory_admin TO CURRENT_USER "
                "WITH INHERIT FALSE, SET TRUE"
            )
        )
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "REVOKE agents_factory_app, agents_factory_admin FROM CURRENT_USER"
                )
            )
        await engine.dispose()


@pytest.fixture
def session_factory(
    database_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(database_engine, expire_on_commit=False)


async def _clear_foundation_data(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
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
                "ALTER TABLE public.action_events "
                "DISABLE TRIGGER action_events_append_only"
            )
        )
        for table_name, trigger_name in (
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
                "TRUNCATE TABLE public.knowledge_chunks, "
                "public.knowledge_ingestion_artifacts, "
                "public.knowledge_ingestions, public.knowledge_version_members, "
                "public.knowledge_versions, public.knowledge_documents, "
                "public.structured_facts, public.knowledge_source_versions, "
                "public.knowledge_sources, public.action_events, public.actions, "
                "public.agent_spec_deployments, "
                "public.agent_spec_versions, public.agent_instances, "
                "public.identity_evidence, public.identity_challenges, "
                "public.identity_subjects, "
                "public.outbound_messages, "
                "public.whatsapp_templates, public.conversation_state_events, "
                "public.messages, public.conversations, "
                "public.whatsapp_webhook_events, "
                "public.whatsapp_accounts, public.secret_envelopes, "
                "public.dead_letter_jobs, "
                "public.job_attempts, public.outbox_jobs, public.audit_events, "
                "public.platform_admins, public.tenants CASCADE"
            )
        )
        await connection.execute(
            text(
                "ALTER TABLE public.action_events "
                "ENABLE TRIGGER action_events_append_only"
            )
        )
        for table_name, trigger_name in (
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
        await connection.execute(
            text("DELETE FROM auth.users WHERE email LIKE 'task5-%@example.test'")
        )


@pytest_asyncio.fixture
async def seeded_world(database_engine: AsyncEngine) -> AsyncIterator[SeededWorld]:
    await _clear_foundation_data(database_engine)
    tenant_a = uuid4()
    tenant_b = uuid4()
    row_a = {
        registration.table_name: uuid4() for registration in TENANT_ISOLATION_REGISTRY
    }
    row_b = {
        registration.table_name: uuid4() for registration in TENANT_ISOLATION_REGISTRY
    }
    row_a["public.tenants"] = tenant_a
    row_b["public.tenants"] = tenant_b
    row_a["public.media_observations"] = row_a["public.messages"]
    row_b["public.media_observations"] = row_b["public.messages"]
    row_a["public.knowledge_proposals"] = row_a["public.knowledge_ingestion_artifacts"]
    row_b["public.knowledge_proposals"] = row_b["public.knowledge_ingestion_artifacts"]
    insert_parent_a = uuid4()
    insert_parent_b = uuid4()
    whatsapp_account_a = row_a["public.whatsapp_accounts"]
    whatsapp_account_b = row_b["public.whatsapp_accounts"]

    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES "
                "(:tenant_a, 'task5-a', 'Task 5 A'), "
                "(:tenant_b, 'task5-b', 'Task 5 B')"
            ),
            {"tenant_a": tenant_a, "tenant_b": tenant_b},
        )
        for tenant_id, rows, label, insert_parent in (
            (tenant_a, row_a, "a", insert_parent_a),
            (tenant_b, row_b, "b", insert_parent_b),
        ):
            completed_ingestion_id = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO public.agent_instances "
                    "(id, tenant_id, product) VALUES "
                    "(:id, :tenant_id, 'Agent Customer Service')"
                ),
                {
                    "id": rows["public.agent_instances"],
                    "tenant_id": tenant_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.agent_spec_versions "
                    "(id, tenant_id, agent_instance_id, version_number, state, "
                    "configuration) VALUES "
                    "(:id, :tenant_id, :instance_id, 1, 'DRAFT', "
                    "jsonb_build_object("
                    "'knowledge', jsonb_build_object("
                    "'digest', CAST(:digest AS text)), "
                    "'code_digest', CAST(:digest AS text)))"
                ),
                {
                    "id": rows["public.agent_spec_versions"],
                    "tenant_id": tenant_id,
                    "instance_id": rows["public.agent_instances"],
                    "digest": "a" * 64,
                },
            )
            await connection.execute(
                text(
                    "UPDATE public.agent_spec_versions SET state = 'TEST', "
                    "compiled_spec = '{}'::jsonb, compiled_digest = :digest "
                    "WHERE id = :id"
                ),
                {"id": rows["public.agent_spec_versions"], "digest": "a" * 64},
            )
            await connection.execute(
                text(
                    "UPDATE public.agent_spec_versions SET state = 'QUALITY_GATE' "
                    "WHERE id = :id"
                ),
                {"id": rows["public.agent_spec_versions"]},
            )
            await connection.execute(
                text(
                    "UPDATE public.agent_spec_versions SET state = 'PRODUCTION' "
                    "WHERE id = :id"
                ),
                {"id": rows["public.agent_spec_versions"]},
            )
            await connection.execute(
                text(
                    "INSERT INTO public.agent_spec_deployments "
                    "(id, tenant_id, agent_instance_id, version_id, action, "
                    "agent_spec_digest, knowledge_digest, code_digest, "
                    "quality_gate_decision_id) VALUES "
                    "(:id, :tenant_id, :instance_id, :version_id, 'PUBLISH', "
                    ":digest, :digest, :digest, :decision_id)"
                ),
                {
                    "id": rows["public.agent_spec_deployments"],
                    "tenant_id": tenant_id,
                    "instance_id": rows["public.agent_instances"],
                    "version_id": rows["public.agent_spec_versions"],
                    "digest": "a" * 64,
                    "decision_id": uuid4(),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_sources "
                    "(id, tenant_id, name, source_type, authority) VALUES "
                    "(:id, :tenant_id, :name, 'MANUAL', 'AUTHORITATIVE')"
                ),
                {
                    "id": rows["public.knowledge_sources"],
                    "tenant_id": tenant_id,
                    "name": f"Task 5 Knowledge {label}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_source_versions "
                    "(id, tenant_id, source_id, version_number, authority, "
                    "content_digest, verified_at, approved_by_admin_id, locator) "
                    "VALUES (:id, :tenant_id, :source_id, 1, 'AUTHORITATIVE', "
                    ":digest, now(), :admin_id, '{}'::jsonb)"
                ),
                {
                    "id": rows["public.knowledge_source_versions"],
                    "tenant_id": tenant_id,
                    "source_id": rows["public.knowledge_sources"],
                    "digest": "e" * 64,
                    "admin_id": uuid4(),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.structured_facts "
                    "(id, tenant_id, source_id, source_version_id, key, kind, "
                    "value, content_digest) VALUES (:id, :tenant_id, :source_id, "
                    ":source_version_id, 'operations.business_hours.main', "
                    "'BUSINESS_HOURS', '{}'::jsonb, :digest)"
                ),
                {
                    "id": rows["public.structured_facts"],
                    "tenant_id": tenant_id,
                    "source_id": rows["public.knowledge_sources"],
                    "source_version_id": rows["public.knowledge_source_versions"],
                    "digest": "f" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_documents "
                    "(id, tenant_id, source_id, source_version_id, category, title, "
                    "document_text, locator, content_digest) VALUES "
                    "(:id, :tenant_id, :source_id, :source_version_id, 'POLICY', "
                    "'Task 5 Policy', 'Tenant-scoped policy.', '{}'::jsonb, :digest)"
                ),
                {
                    "id": rows["public.knowledge_documents"],
                    "tenant_id": tenant_id,
                    "source_id": rows["public.knowledge_sources"],
                    "source_version_id": rows["public.knowledge_source_versions"],
                    "digest": "0" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_versions "
                    "(id, tenant_id, name, version_number, state) "
                    "VALUES (:id, :tenant_id, 'Task 5 v1', 1, 'DRAFT')"
                ),
                {
                    "id": rows["public.knowledge_versions"],
                    "tenant_id": tenant_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_version_members "
                    "(id, tenant_id, knowledge_version_id, structured_fact_id, "
                    "position) VALUES (:id, :tenant_id, :version_id, :fact_id, 0)"
                ),
                {
                    "id": rows["public.knowledge_version_members"],
                    "tenant_id": tenant_id,
                    "version_id": rows["public.knowledge_versions"],
                    "fact_id": rows["public.structured_facts"],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_chunks "
                    "(id, tenant_id, knowledge_version_id, document_id, source_id, "
                    "source_version_id, authority, chunk_index, chunk_text, "
                    "content_digest, locale, locator, embedding, embedding_model, "
                    "embedding_version) VALUES (:id, :tenant_id, :version_id, "
                    ":document_id, :source_id, :source_version_id, 'AUTHORITATIVE', "
                    "0, 'Task 5 policy.', :digest, 'en-US', '{}'::jsonb, "
                    "CAST(:embedding AS extensions.vector), 'deterministic-sha256', '1')"
                ),
                {
                    "id": rows["public.knowledge_chunks"],
                    "tenant_id": tenant_id,
                    "version_id": rows["public.knowledge_versions"],
                    "document_id": rows["public.knowledge_documents"],
                    "source_id": rows["public.knowledge_sources"],
                    "source_version_id": rows["public.knowledge_source_versions"],
                    "digest": "2" * 64,
                    "embedding": "[" + ",".join(("0",) * 1536) + "]",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_ingestions "
                    "(id, tenant_id, source_id, state) "
                    "VALUES (:id, :tenant_id, :source_id, 'PENDING')"
                ),
                {
                    "id": rows["public.knowledge_ingestions"],
                    "tenant_id": tenant_id,
                    "source_id": rows["public.knowledge_sources"],
                },
            )
            await connection.execute(
                text(
                    "UPDATE public.knowledge_ingestions SET state = 'PROCESSING', "
                    "updated_at = now() WHERE id = :id"
                ),
                {"id": rows["public.knowledge_ingestions"]},
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_ingestion_artifacts "
                    "(id, tenant_id, source_id, ingestion_id, artifact_type, "
                    "artifact_digest, proposal) VALUES "
                    "(:id, :tenant_id, :source_id, :ingestion_id, 'DOCUMENT', "
                    ":digest, '{}'::jsonb)"
                ),
                {
                    "id": rows["public.knowledge_ingestion_artifacts"],
                    "tenant_id": tenant_id,
                    "source_id": rows["public.knowledge_sources"],
                    "ingestion_id": rows["public.knowledge_ingestions"],
                    "digest": "1" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_ingestions "
                    "(id, tenant_id, source_id, state) "
                    "VALUES (:id, :tenant_id, :source_id, 'PENDING')"
                ),
                {
                    "id": completed_ingestion_id,
                    "tenant_id": tenant_id,
                    "source_id": rows["public.knowledge_sources"],
                },
            )
            await connection.execute(
                text(
                    "UPDATE public.knowledge_ingestions SET state = 'PROCESSING', "
                    "updated_at = now() WHERE id = :id"
                ),
                {"id": completed_ingestion_id},
            )
            await connection.execute(
                text(
                    "UPDATE public.knowledge_ingestions SET state = 'SUCCEEDED', "
                    "content_digest = :digest, storage_path = :storage_path, "
                    "completed_at = now(), updated_at = now() WHERE id = :id"
                ),
                {
                    "id": completed_ingestion_id,
                    "digest": "3" * 64,
                    "storage_path": f"{tenant_id}/task5/source.bin",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_conflicts "
                    "(id, tenant_id, proposal_id, fact_key, critical, "
                    "proposed_authority, existing_authority, existing_fact_id) "
                    "VALUES (:id, :tenant_id, :proposal_id, "
                    "'operations.business_hours.main', true, 'AUTHORITATIVE', "
                    "'AUTHORITATIVE', :fact_id)"
                ),
                {
                    "id": rows["public.knowledge_conflicts"],
                    "tenant_id": tenant_id,
                    "proposal_id": rows["public.knowledge_proposals"],
                    "fact_id": rows["public.structured_facts"],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_source_diffs "
                    "(id, tenant_id, source_id, ingestion_id, draft_version_id, "
                    "previous_digest, current_digest) VALUES "
                    "(:id, :tenant_id, :source_id, :ingestion_id, :version_id, "
                    ":previous_digest, :current_digest)"
                ),
                {
                    "id": rows["public.knowledge_source_diffs"],
                    "tenant_id": tenant_id,
                    "source_id": rows["public.knowledge_sources"],
                    "ingestion_id": completed_ingestion_id,
                    "version_id": rows["public.knowledge_versions"],
                    "previous_digest": "e" * 64,
                    "current_digest": "3" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.knowledge_eval_evidence "
                    "(id, tenant_id, knowledge_version_id, knowledge_digest, "
                    "suite_digest, runner_version, passed, passed_cases, failed_cases) "
                    "VALUES (:id, :tenant_id, :version_id, :digest, :suite_digest, "
                    "'0.1.0', true, 1, 0)"
                ),
                {
                    "id": rows["public.knowledge_eval_evidence"],
                    "tenant_id": tenant_id,
                    "version_id": rows["public.knowledge_versions"],
                    "digest": "4" * 64,
                    "suite_digest": "5" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.identity_subjects "
                    "(id, tenant_id, customer_ref, whatsapp_recognized_at) "
                    "VALUES (:id, :tenant_id, :customer_ref, now())"
                ),
                {
                    "id": rows["public.identity_subjects"],
                    "tenant_id": tenant_id,
                    "customer_ref": f"task5-customer-{label}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.identity_challenges "
                    "(id, tenant_id, customer_ref, required_level, method, "
                    "secret_digest, status, attempts, max_attempts, expires_at, "
                    "created_at) VALUES (:id, :tenant_id, :customer_ref, 2, "
                    "'ADDITIONAL_VERIFICATION', :digest, 'PENDING', 0, 5, "
                    "now() + interval '1 hour', now())"
                ),
                {
                    "id": rows["public.identity_challenges"],
                    "tenant_id": tenant_id,
                    "customer_ref": f"task5-customer-{label}",
                    "digest": "b" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.identity_evidence "
                    "(id, tenant_id, customer_ref, method, result, "
                    "achieved_level, scope, bound_action_ref, "
                    "evidence_ref_digest, verified_at, expires_at) VALUES "
                    "(:id, :tenant_id, :customer_ref, 'OTP', 'VERIFIED', 3, "
                    "'ACTION', :action_ref, :digest, now(), "
                    "now() + interval '1 hour')"
                ),
                {
                    "id": rows["public.identity_evidence"],
                    "tenant_id": tenant_id,
                    "customer_ref": f"task5-customer-{label}",
                    "action_ref": f"task5-action-{label}",
                    "digest": "c" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.audit_events "
                    "(id, tenant_id, actor_type, event_type, entity_type, "
                    "correlation_id) VALUES "
                    "(:id, :tenant_id, 'system', 'task5.seeded', 'tenant', "
                    ":correlation_id)"
                ),
                {
                    "id": rows["public.audit_events"],
                    "tenant_id": tenant_id,
                    "correlation_id": uuid4(),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.outbox_jobs "
                    "(id, tenant_id, idempotency_key, topic, available_at) VALUES "
                    "(:id, :tenant_id, :key, 'task5.seeded', now()), "
                    "(:insert_parent, :tenant_id, :parent_key, "
                    "'task5.insert-parent', now())"
                ),
                {
                    "id": rows["public.outbox_jobs"],
                    "insert_parent": insert_parent,
                    "tenant_id": tenant_id,
                    "key": f"task5-seeded-{label}",
                    "parent_key": f"task5-insert-parent-{label}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.job_attempts "
                    "(id, tenant_id, outbox_job_id, attempt_number, status) "
                    "VALUES (:id, :tenant_id, :outbox_job_id, 1, 'started')"
                ),
                {
                    "id": rows["public.job_attempts"],
                    "tenant_id": tenant_id,
                    "outbox_job_id": rows["public.outbox_jobs"],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.dead_letter_jobs "
                    "(id, tenant_id, outbox_job_id, reason_code) "
                    "VALUES (:id, :tenant_id, :outbox_job_id, 'task5-seeded')"
                ),
                {
                    "id": rows["public.dead_letter_jobs"],
                    "tenant_id": tenant_id,
                    "outbox_job_id": rows["public.outbox_jobs"],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.secret_envelopes "
                    "(id, tenant_id, purpose, record_context, ciphertext, "
                    "wrapped_data_key, payload_nonce, key_nonce, algorithm, "
                    "format_version, key_id, key_version) VALUES "
                    "(:id, :tenant_id, 'task5.seeded', :record_context, "
                    ":ciphertext, :wrapped_data_key, :payload_nonce, :key_nonce, "
                    "'AES-256-GCM', 1, 'task5-matrix-key', 1)"
                ),
                {
                    "id": rows["public.secret_envelopes"],
                    "tenant_id": tenant_id,
                    "record_context": f"task5-seeded-{label}",
                    "ciphertext": uuid4().bytes + uuid4().bytes,
                    "wrapped_data_key": uuid4().bytes * 3,
                    "payload_nonce": uuid4().bytes[:12],
                    "key_nonce": uuid4().bytes[:12],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.integration_connections "
                    "(id, tenant_id, connector_name, auth_kind) "
                    "VALUES (:id, :tenant_id, 'woocommerce', 'API_KEY')"
                ),
                {"id": rows["public.integration_connections"], "tenant_id": tenant_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO public.whatsapp_accounts "
                    "(id, tenant_id, provider, waba_id, phone_number_id, status) "
                    "VALUES (:id, :tenant_id, 'meta', :waba_id, :phone_number_id, "
                    "'active')"
                ),
                {
                    "id": rows["public.whatsapp_accounts"],
                    "tenant_id": tenant_id,
                    "waba_id": f"task5-waba-{label}",
                    "phone_number_id": f"task5-phone-{label}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.whatsapp_webhook_events "
                    "(id, tenant_id, whatsapp_account_id, whatsapp_message_id, "
                    "sender_wa_id, message_type, provider_timestamp, raw_payload) "
                    "VALUES (:id, :tenant_id, :account_id, :message_id, "
                    "'573000000001', 'text', now(), '{}'::jsonb)"
                ),
                {
                    "id": rows["public.whatsapp_webhook_events"],
                    "tenant_id": tenant_id,
                    "account_id": rows["public.whatsapp_accounts"],
                    "message_id": f"task5-message-{label}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.conversations "
                    "(id, tenant_id, whatsapp_account_id, customer_wa_id) "
                    "VALUES (:id, :tenant_id, :account_id, :customer_wa_id)"
                ),
                {
                    "id": rows["public.conversations"],
                    "tenant_id": tenant_id,
                    "account_id": rows["public.whatsapp_accounts"],
                    "customer_wa_id": f"57300000000{1 if label == 'a' else 2}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.actions "
                    "(id, tenant_id, conversation_id, customer_ref, capability, "
                    "action_type, risk, required_identity_level, "
                    "achieved_identity_level, parameters, parameter_digest, "
                    "confirmation_required, approval_required, "
                    "connector_binding_id, connector_name, state, created_at, "
                    "updated_at) VALUES (:id, :tenant_id, :conversation_id, "
                    ":customer_ref, 'orders', 'orders.get_status', 'LOW', 1, 1, "
                    "'{}'::jsonb, :digest, false, false, :binding_id, "
                    "'woocommerce', 'REQUESTED', now(), now())"
                ),
                {
                    "id": rows["public.actions"],
                    "tenant_id": tenant_id,
                    "conversation_id": rows["public.conversations"],
                    "customer_ref": f"task5-customer-{label}",
                    "digest": "d" * 64,
                    "binding_id": uuid4(),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.action_events "
                    "(id, tenant_id, action_id, version, from_state, to_state, "
                    "event_type, payload, created_at) VALUES "
                    "(:id, :tenant_id, :action_id, 1, NULL, 'REQUESTED', "
                    "'action.requested', '{}'::jsonb, now())"
                ),
                {
                    "id": rows["public.action_events"],
                    "tenant_id": tenant_id,
                    "action_id": rows["public.actions"],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.conversation_state_events "
                    "(id, tenant_id, conversation_id, from_state, to_state, "
                    "version, actor_type, reason) VALUES "
                    "(:id, :tenant_id, :conversation_id, NULL, 'AI_ACTIVE', "
                    "1, 'system', 'task5_seeded')"
                ),
                {
                    "id": rows["public.conversation_state_events"],
                    "tenant_id": tenant_id,
                    "conversation_id": rows["public.conversations"],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.messages "
                    "(id, tenant_id, conversation_id, source_event_id, direction, "
                    "sender_type, provider_message_id, message_type, content, "
                    "provider_timestamp, arrival_sequence) VALUES "
                    "(:id, :tenant_id, :conversation_id, :source_event_id, "
                    "'inbound', 'customer', :provider_message_id, 'text', "
                    "'{}'::jsonb, now(), 1)"
                ),
                {
                    "id": rows["public.messages"],
                    "tenant_id": tenant_id,
                    "conversation_id": rows["public.conversations"],
                    "source_event_id": rows["public.whatsapp_webhook_events"],
                    "provider_message_id": f"task5-message-{label}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.whatsapp_templates "
                    "(id, tenant_id, whatsapp_account_id, provider_template_id, "
                    "name, language, status, category, variable_names) VALUES "
                    "(:id, :tenant_id, :account_id, :provider_template_id, "
                    "'task5_template', 'es_CO', 'APPROVED', 'UTILITY', "
                    "'[]'::jsonb)"
                ),
                {
                    "id": rows["public.whatsapp_templates"],
                    "tenant_id": tenant_id,
                    "account_id": rows["public.whatsapp_accounts"],
                    "provider_template_id": f"task5-template-{label}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.outbound_messages "
                    "(id, tenant_id, whatsapp_account_id, whatsapp_template_id, "
                    "recipient_wa_id, kind, idempotency_key, payload) VALUES "
                    "(:id, :tenant_id, :account_id, :template_id, "
                    "'573000000001', 'template', :idempotency_key, "
                    '\'{"template_name":"task5_template",'
                    '"language":"es_CO","body_parameters":[]}\'::jsonb)'
                ),
                {
                    "id": rows["public.outbound_messages"],
                    "tenant_id": tenant_id,
                    "account_id": rows["public.whatsapp_accounts"],
                    "template_id": rows["public.whatsapp_templates"],
                    "idempotency_key": f"task5-outbound-{label}",
                },
            )

            await connection.execute(
                text(
                    "INSERT INTO public.appointment_configurations (id, tenant_id, connection_id, configuration) VALUES (:id, :tenant, :connection, '{}'::jsonb)"
                ),
                {
                    "id": rows["public.appointment_configurations"],
                    "tenant": tenant_id,
                    "connection": rows["public.integration_connections"],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.appointments (id, tenant_id, customer_ref, conversation_id, service_id, professional_id, location_id, start_at, end_at, busy_start, busy_end, external_event_id, etag, status, revision, last_action_id) VALUES (:id, :tenant, 'fixture', :conversation, 'service', 'professional', 'location', now(), now() + interval '30 minutes', now(), now() + interval '30 minutes', :external_id, 'fixture-etag', 'BOOKED', 1, :action)"
                ),
                {
                    "id": rows["public.appointments"],
                    "tenant": tenant_id,
                    "conversation": rows["public.conversations"],
                    "external_id": f"fixture-{tenant_id}",
                    "action": rows["public.actions"],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.appointment_operations (id, tenant_id, operation, parameter_digest, status) VALUES (:id, :tenant, 'appointments.create_appointment', :digest, 'CLAIMED')"
                ),
                {
                    "id": rows["public.appointment_operations"],
                    "tenant": tenant_id,
                    "digest": "0" * 64,
                },
            )

            await connection.execute(
                text(
                    "INSERT INTO public.order_operations(id, tenant_id, binding_id, operation, parameter_digest, status) VALUES (:id, :tenant, :binding, 'orders.add_order_note', :digest, 'CLAIMED')"
                ),
                {
                    "id": rows["public.order_operations"],
                    "tenant": tenant_id,
                    "binding": uuid4(),
                    "digest": "0" * 64,
                },
            )

            await connection.execute(
                text(
                    "INSERT INTO public.media_evidence(id,tenant_id,whatsapp_account_id,provider_media_id,customer_ref,first_message_id,kind,status,expires_at) VALUES (:id,:tenant,:account,'2700','media-fixture',:message,'image','PROCESSING',now()+interval '90 days')"
                ),
                {
                    "id": rows["public.media_evidence"],
                    "tenant": tenant_id,
                    "account": rows["public.whatsapp_accounts"],
                    "message": rows["public.messages"],
                },
            )

            await connection.execute(
                text(
                    "INSERT INTO public.media_observations(id,tenant_id,media_id,observation) VALUES (:id,:tenant,:media,'{}')"
                ),
                {
                    "id": rows["public.media_observations"],
                    "tenant": tenant_id,
                    "media": rows["public.media_evidence"],
                },
            )

            await connection.execute(
                text(
                    "INSERT INTO public.cases(id,tenant_id,customer_ref,capability,issue_type,binding_id,resource_id,deduplication_key,content_digest,intake,revision,status,priority,policy,approaching_at,target_at,created_at,updated_at) VALUES (:id,:tenant,'fixture','orders','delivery_delay',:binding,'order',:digest,:digest,'{}',1,'OPEN','NORMAL','{}',now()+interval '20 hours',now()+interval '24 hours',now(),now())"
                ),
                {
                    "id": rows["public.cases"],
                    "tenant": tenant_id,
                    "binding": uuid4(),
                    "digest": "0" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.case_events(id,tenant_id,case_id,revision,event_type,actor_id,actor_type,correlation_id,reason,to_status) VALUES (:id,:tenant,:case,1,'CREATED',:actor,'system',:actor,'fixture','OPEN')"
                ),
                {
                    "id": rows["public.case_events"],
                    "tenant": tenant_id,
                    "case": rows["public.cases"],
                    "actor": uuid4(),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.case_operations(id,tenant_id,customer_ref,case_id,parameter_digest,receipt) VALUES (:id,:tenant,'fixture',:case,:digest,'{}')"
                ),
                {
                    "id": rows["public.case_operations"],
                    "tenant": tenant_id,
                    "case": rows["public.cases"],
                    "digest": "0" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.case_delivery_operations(id,tenant_id,effect_key,parameter_digest,operation,status) VALUES (:id,:tenant,'fixture',:digest,'sheets.update_row','CLAIMED')"
                ),
                {
                    "id": rows["public.case_delivery_operations"],
                    "tenant": tenant_id,
                    "digest": "0" * 64,
                },
            )

    world = SeededWorld(
        tenant_a=tenant_a,
        tenant_b=tenant_b,
        row_a=row_a,
        row_b=row_b,
        insert_parent_a=insert_parent_a,
        insert_parent_b=insert_parent_b,
        whatsapp_account_a=whatsapp_account_a,
        whatsapp_account_b=whatsapp_account_b,
    )
    try:
        yield world
    finally:
        await _clear_foundation_data(database_engine)


async def _prepare_app_session(session: AsyncSession, context: object) -> None:
    await session.execute(text("SET LOCAL ROLE agents_factory_app"))
    if context not in (MISSING_CONTEXT, RESET_CONTEXT):
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(context)},
        )


def _normalize_error_text(value: object) -> str | None:
    if value is None:
        return None
    return UUID_PATTERN.sub("<uuid>", str(value))


def _denial_fingerprint(error: DBAPIError) -> DenialFingerprint:
    origin = error.orig
    assert origin is not None
    cause = origin.__cause__ or origin
    sqlstate = getattr(cause, "sqlstate", None) or getattr(origin, "sqlstate", None)
    assert isinstance(sqlstate, str)
    return DenialFingerprint(
        exception_type=type(cause).__name__,
        sqlstate=sqlstate,
        message=_normalize_error_text(cause) or "",
        detail=_normalize_error_text(getattr(cause, "detail", None)),
        schema_name=_normalize_error_text(getattr(cause, "schema_name", None)),
        table_name=_normalize_error_text(getattr(cause, "table_name", None)),
        constraint_name=_normalize_error_text(getattr(cause, "constraint_name", None)),
    )


async def _resolve_context_after_optional_reset(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    context: object,
    reset_tenant_id: UUID,
) -> object:
    if context is not RESET_CONTEXT:
        return context
    async with session_factory.begin() as session:
        await _prepare_app_session(session, reset_tenant_id)
        await session.execute(text("SELECT 1"))
    return MISSING_CONTEXT


async def _denied_fingerprint(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    context: object,
    reset_tenant_id: UUID,
    statement: str,
    parameters: dict[str, object],
) -> DenialFingerprint:
    effective_context = await _resolve_context_after_optional_reset(
        session_factory,
        context=context,
        reset_tenant_id=reset_tenant_id,
    )
    with pytest.raises(DBAPIError) as caught:
        async with session_factory.begin() as session:
            await _prepare_app_session(session, effective_context)
            await session.execute(text(statement), parameters)
    return _denial_fingerprint(caught.value)


async def _returning_ids(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    context: object,
    reset_tenant_id: UUID,
    statement: str,
    parameters: dict[str, object],
) -> list[UUID]:
    effective_context = await _resolve_context_after_optional_reset(
        session_factory,
        context=context,
        reset_tenant_id=reset_tenant_id,
    )
    async with session_factory.begin() as session:
        await _prepare_app_session(session, effective_context)
        result = await session.execute(text(statement), parameters)
    return list(result.scalars())


async def _discover_tenant_owned_tables(
    connection: AsyncConnection,
) -> set[tuple[str, str]]:
    rows = (
        await connection.execute(
            text(
                "SELECT format('%I.%I', namespace.nspname, relation.relname), "
                "attribute.attname "
                "FROM pg_class AS relation "
                "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
                "JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r', 'p') "
                "AND NOT attribute.attisdropped "
                "AND (attribute.attname = 'tenant_id' "
                "OR (relation.relname = 'tenants' AND attribute.attname = 'id'))"
            )
        )
    ).all()
    return {(str(row[0]), str(row[1])) for row in rows}


def _insert_statement(table_name: str) -> str:
    statements = {
        "public.cases": "INSERT INTO public.cases(id,tenant_id) VALUES (:id,:tenant_id)",
        "public.case_events": "INSERT INTO public.case_events(id,tenant_id) VALUES (:id,:tenant_id)",
        "public.case_operations": "INSERT INTO public.case_operations(id,tenant_id) VALUES (:id,:tenant_id)",
        "public.case_delivery_operations": "INSERT INTO public.case_delivery_operations(id,tenant_id) VALUES (:id,:tenant_id)",
        "public.media_observations": "INSERT INTO public.media_observations (id, tenant_id) VALUES (:id, :tenant_id)",
        "public.media_evidence": "INSERT INTO public.media_evidence (id, tenant_id) VALUES (:id, :tenant_id)",
        "public.order_operations": "INSERT INTO public.order_operations (id, tenant_id) VALUES (:id, :tenant_id)",
        "public.appointment_configurations": "INSERT INTO public.appointment_configurations (id, tenant_id) VALUES (:id, :tenant_id)",
        "public.appointments": "INSERT INTO public.appointments (id, tenant_id) VALUES (:id, :tenant_id)",
        "public.appointment_operations": "INSERT INTO public.appointment_operations (id, tenant_id) VALUES (:id, :tenant_id)",
        "public.integration_connections": (
            "INSERT INTO public.integration_connections "
            "(id, tenant_id, connector_name, auth_kind) "
            "VALUES (:id, :tenant_id, 'woocommerce', 'API_KEY')"
        ),
        "public.tenants": (
            "INSERT INTO public.tenants (id, slug, name) "
            "VALUES (:id, :slug, 'Task 5 inserted tenant')"
        ),
        "public.audit_events": (
            "INSERT INTO public.audit_events "
            "(id, tenant_id, actor_type, event_type, entity_type, correlation_id) "
            "VALUES (:id, :tenant_id, 'system', 'task5.insert', 'tenant', "
            ":correlation_id)"
        ),
        "public.outbox_jobs": (
            "INSERT INTO public.outbox_jobs "
            "(id, tenant_id, idempotency_key, topic, available_at) "
            "VALUES (:id, :tenant_id, :key, 'task5.insert', now())"
        ),
        "public.job_attempts": (
            "INSERT INTO public.job_attempts "
            "(id, tenant_id, outbox_job_id, attempt_number, status) "
            "VALUES (:id, :tenant_id, :outbox_job_id, 1, 'started')"
        ),
        "public.dead_letter_jobs": (
            "INSERT INTO public.dead_letter_jobs "
            "(id, tenant_id, outbox_job_id, reason_code) "
            "VALUES (:id, :tenant_id, :outbox_job_id, 'task5-insert')"
        ),
        "public.secret_envelopes": (
            "INSERT INTO public.secret_envelopes "
            "(id, tenant_id, purpose, record_context, ciphertext, "
            "wrapped_data_key, payload_nonce, key_nonce, algorithm, "
            "format_version, key_id, key_version) VALUES "
            "(:id, :tenant_id, 'task5.insert', :record_context, :ciphertext, "
            ":wrapped_data_key, :payload_nonce, :key_nonce, 'AES-256-GCM', "
            "1, 'task5-matrix-key', 1)"
        ),
        "public.whatsapp_accounts": (
            "INSERT INTO public.whatsapp_accounts "
            "(id, tenant_id, provider, waba_id, phone_number_id, status) "
            "VALUES (:id, :tenant_id, 'meta', :waba_id, :phone_number_id, "
            "'active')"
        ),
        "public.whatsapp_webhook_events": (
            "INSERT INTO public.whatsapp_webhook_events "
            "(id, tenant_id, whatsapp_account_id, whatsapp_message_id, "
            "sender_wa_id, message_type, provider_timestamp, raw_payload) "
            "VALUES (:id, :tenant_id, :whatsapp_account_id, :message_id, "
            "'573000000001', 'text', now(), '{}'::jsonb)"
        ),
        "public.whatsapp_templates": (
            "INSERT INTO public.whatsapp_templates "
            "(id, tenant_id, whatsapp_account_id, provider_template_id, name, "
            "language, status, category, variable_names) VALUES "
            "(:id, :tenant_id, :whatsapp_account_id, :provider_template_id, "
            ":template_name, 'es_CO', 'APPROVED', 'UTILITY', '[]'::jsonb)"
        ),
        "public.conversations": (
            "INSERT INTO public.conversations "
            "(id, tenant_id, whatsapp_account_id, customer_wa_id) "
            "VALUES (:id, :tenant_id, :whatsapp_account_id, :customer_wa_id)"
        ),
        "public.messages": (
            "INSERT INTO public.messages "
            "(id, tenant_id, conversation_id, direction, sender_type, "
            "provider_message_id, message_type, content, provider_timestamp, "
            "arrival_sequence) VALUES (:id, :tenant_id, :conversation_id, "
            "'inbound', 'customer', :message_id, 'text', '{}'::jsonb, now(), "
            ":arrival_sequence)"
        ),
        "public.conversation_state_events": (
            "INSERT INTO public.conversation_state_events "
            "(id, tenant_id, conversation_id, from_state, to_state, version, "
            "actor_type, reason) VALUES (:id, :tenant_id, :conversation_id, "
            "'AI_ACTIVE', 'AWAITING_HUMAN', :version, 'system', 'task5_insert')"
        ),
        "public.outbound_messages": (
            "INSERT INTO public.outbound_messages "
            "(id, tenant_id, whatsapp_account_id, whatsapp_template_id, "
            "recipient_wa_id, kind, idempotency_key, payload) VALUES "
            "(:id, :tenant_id, :whatsapp_account_id, "
            "(SELECT id FROM public.whatsapp_templates "
            " WHERE tenant_id = :tenant_id "
            " AND whatsapp_account_id = :whatsapp_account_id LIMIT 1), "
            "'573000000001', 'template', :idempotency_key, "
            '\'{"template_name":"task5_template",'
            '"language":"es_CO","body_parameters":[]}\'::jsonb)'
        ),
        "public.agent_instances": (
            "INSERT INTO public.agent_instances (id, tenant_id, product) "
            "VALUES (:id, :tenant_id, 'Agent Customer Service')"
        ),
        "public.agent_spec_versions": (
            "INSERT INTO public.agent_spec_versions "
            "(id, tenant_id, agent_instance_id, version_number, state, "
            "configuration) VALUES (:id, :tenant_id, :parent_id, :version, "
            "'DRAFT', '{}'::jsonb)"
        ),
        "public.agent_spec_deployments": (
            "INSERT INTO public.agent_spec_deployments "
            "(id, tenant_id, agent_instance_id, version_id, action, "
            "agent_spec_digest, knowledge_digest, code_digest, "
            "quality_gate_decision_id) VALUES (:id, :tenant_id, "
            "(SELECT agent_instance_id FROM public.agent_spec_versions "
            "WHERE tenant_id = :tenant_id AND id = :parent_id), :parent_id, "
            "'ROLLBACK', :digest, :digest, :digest, :correlation_id)"
        ),
        "public.knowledge_sources": (
            "INSERT INTO public.knowledge_sources "
            "(id, tenant_id, name, source_type, authority) VALUES "
            "(:id, :tenant_id, :name, 'MANUAL', 'AUTHORITATIVE')"
        ),
        "public.knowledge_source_versions": (
            "INSERT INTO public.knowledge_source_versions "
            "(id, tenant_id, source_id, version_number, authority, content_digest, "
            "verified_at, approved_by_admin_id, locator) VALUES "
            "(:id, :tenant_id, :parent_id, :version, 'AUTHORITATIVE', :digest, "
            "now(), :correlation_id, '{}'::jsonb)"
        ),
        "public.structured_facts": (
            "INSERT INTO public.structured_facts "
            "(id, tenant_id, source_id, source_version_id, key, kind, value, "
            "content_digest) SELECT :id, :tenant_id, source_id, id, "
            "'operations.business_hours.insert', 'BUSINESS_HOURS', '{}'::jsonb, "
            ":digest FROM public.knowledge_source_versions "
            "WHERE tenant_id = :tenant_id AND id = :parent_id"
        ),
        "public.knowledge_documents": (
            "INSERT INTO public.knowledge_documents "
            "(id, tenant_id, source_id, source_version_id, category, title, "
            "document_text, locator, content_digest) SELECT :id, :tenant_id, "
            "source_id, id, 'POLICY', 'Task 5 insert', 'Policy.', '{}'::jsonb, "
            ":digest FROM public.knowledge_source_versions "
            "WHERE tenant_id = :tenant_id AND id = :parent_id"
        ),
        "public.knowledge_versions": (
            "INSERT INTO public.knowledge_versions "
            "(id, tenant_id, name, version_number, state) "
            "VALUES (:id, :tenant_id, :name, :version, 'DRAFT')"
        ),
        "public.knowledge_version_members": (
            "INSERT INTO public.knowledge_version_members "
            "(id, tenant_id, knowledge_version_id, structured_fact_id, position) "
            "SELECT :id, :tenant_id, :parent_id, id, :version "
            "FROM public.structured_facts WHERE tenant_id = :tenant_id LIMIT 1"
        ),
        "public.knowledge_ingestions": (
            "INSERT INTO public.knowledge_ingestions "
            "(id, tenant_id, source_id, state) "
            "VALUES (:id, :tenant_id, :parent_id, 'PENDING')"
        ),
        "public.knowledge_ingestion_artifacts": (
            "INSERT INTO public.knowledge_ingestion_artifacts "
            "(id, tenant_id, source_id, ingestion_id, artifact_type, "
            "artifact_digest, proposal) SELECT :id, :tenant_id, source_id, id, "
            "'DOCUMENT', :digest, '{}'::jsonb FROM public.knowledge_ingestions "
            "WHERE tenant_id = :tenant_id AND id = :parent_id"
        ),
        "public.knowledge_chunks": (
            "INSERT INTO public.knowledge_chunks "
            "(id, tenant_id, knowledge_version_id, document_id, source_id, "
            "source_version_id, authority, chunk_index, chunk_text, content_digest, "
            "locale, locator, embedding, embedding_model, embedding_version) "
            "VALUES (:id, :tenant_id, :parent_id, :binding_id, :correlation_id, "
            ":outbox_job_id, 'REFERENCE', 0, 'Task 5 insert', :digest, 'en-US', "
            "'{}'::jsonb, CAST(:embedding AS extensions.vector), "
            "'deterministic-sha256', '1')"
        ),
        "public.knowledge_proposals": (
            "INSERT INTO public.knowledge_proposals "
            "(id, tenant_id, ingestion_artifact_id, ingestion_id, source_id, "
            "artifact_type, proposed_payload, content_digest) SELECT "
            ":id, :tenant_id, artifact.id, artifact.ingestion_id, artifact.source_id, "
            "artifact.artifact_type, artifact.proposal, :digest "
            "FROM public.knowledge_ingestion_artifacts AS artifact "
            "WHERE artifact.tenant_id = :tenant_id AND artifact.id = :parent_id"
        ),
        "public.knowledge_conflicts": (
            "INSERT INTO public.knowledge_conflicts "
            "(id, tenant_id, proposal_id, critical, proposed_authority, "
            "existing_authority) VALUES (:id, :tenant_id, :parent_id, true, "
            "'AUTHORITATIVE', 'AUTHORITATIVE')"
        ),
        "public.knowledge_source_diffs": (
            "INSERT INTO public.knowledge_source_diffs "
            "(id, tenant_id, source_id, ingestion_id, draft_version_id, "
            "current_digest) SELECT :id, :tenant_id, ingestion.source_id, "
            "ingestion.id, :binding_id, :digest FROM public.knowledge_ingestions "
            "AS ingestion WHERE ingestion.tenant_id = :tenant_id "
            "AND ingestion.id = :parent_id"
        ),
        "public.knowledge_eval_evidence": (
            "INSERT INTO public.knowledge_eval_evidence "
            "(id, tenant_id, knowledge_version_id, knowledge_digest, suite_digest, "
            "runner_version, passed, passed_cases, failed_cases) VALUES "
            "(:id, :tenant_id, :parent_id, :digest, :digest, '0.1.0', true, 1, 0)"
        ),
        "public.identity_subjects": (
            "INSERT INTO public.identity_subjects "
            "(id, tenant_id, customer_ref, whatsapp_recognized_at) "
            "VALUES (:id, :tenant_id, :customer_ref, now())"
        ),
        "public.identity_challenges": (
            "INSERT INTO public.identity_challenges "
            "(id, tenant_id, customer_ref, required_level, method, "
            "secret_digest, status, attempts, max_attempts, expires_at, "
            "created_at) VALUES (:id, :tenant_id, :customer_ref, 2, "
            "'ADDITIONAL_VERIFICATION', :digest, 'PENDING', 0, 5, "
            "now() + interval '1 hour', now())"
        ),
        "public.identity_evidence": (
            "INSERT INTO public.identity_evidence "
            "(id, tenant_id, customer_ref, method, result, achieved_level, "
            "scope, bound_action_ref, evidence_ref_digest, verified_at, "
            "expires_at) VALUES (:id, :tenant_id, :customer_ref, 'OTP', "
            "'VERIFIED', 3, 'ACTION', :action_ref, :digest, now(), "
            "now() + interval '1 hour')"
        ),
        "public.actions": (
            "INSERT INTO public.actions "
            "(id, tenant_id, conversation_id, customer_ref, capability, "
            "action_type, risk, required_identity_level, achieved_identity_level, "
            "parameters, parameter_digest, confirmation_required, "
            "approval_required, connector_binding_id, connector_name, state, "
            "created_at, updated_at) VALUES (:id, :tenant_id, :parent_id, "
            ":customer_ref, 'orders', 'orders.get_status', 'LOW', 1, 1, "
            "'{}'::jsonb, :digest, false, false, :binding_id, 'woocommerce', "
            "'REQUESTED', now(), now())"
        ),
        "public.action_events": (
            "INSERT INTO public.action_events "
            "(id, tenant_id, action_id, version, from_state, to_state, "
            "event_type, payload, created_at) VALUES (:id, :tenant_id, "
            ":parent_id, :version, NULL, 'REQUESTED', 'action.requested', "
            "'{}'::jsonb, now())"
        ),
    }
    return statements[table_name]


def _insert_parameters(
    table_name: str,
    *,
    tenant_id: UUID,
    parent_id: UUID,
    nonce: str,
) -> dict[str, object]:
    return {
        "id": tenant_id if table_name == "public.tenants" else uuid4(),
        "tenant_id": tenant_id,
        "slug": f"task5-{nonce}",
        "correlation_id": uuid4(),
        "key": f"task5-{nonce}",
        "outbox_job_id": parent_id,
        "record_context": f"task5-{nonce}",
        "ciphertext": uuid4().bytes + uuid4().bytes,
        "wrapped_data_key": uuid4().bytes * 3,
        "payload_nonce": uuid4().bytes[:12],
        "key_nonce": uuid4().bytes[:12],
        "waba_id": f"task5-waba-{nonce}",
        "phone_number_id": f"task5-phone-{nonce}",
        "whatsapp_account_id": parent_id,
        "conversation_id": parent_id,
        "customer_wa_id": f"573{uuid4().int % 10**9:09d}",
        "customer_ref": f"task5-customer-{nonce}",
        "message_id": f"task5-message-{nonce}",
        "provider_template_id": f"task5-template-{nonce}",
        "template_name": f"task5_{nonce[:80]}",
        "idempotency_key": f"task5-outbound-{nonce}",
        "name": f"Task 5 {nonce[:100]}",
        "arrival_sequence": uuid4().int % 1_000_000_000 + 2,
        "version": uuid4().int % 1_000_000_000 + 2,
        "parent_id": parent_id,
        "digest": "a" * 64,
        "action_ref": f"task5-action-{nonce}",
        "binding_id": uuid4(),
        "embedding": "[" + ",".join(("0",) * 1536) + "]",
    }


def _matching_update(table_name: str) -> str | None:
    return {
        "public.cases": None,
        "public.case_events": None,
        "public.case_operations": None,
        "public.case_delivery_operations": None,
        "public.media_observations": None,
        "public.media_evidence": None,
        "public.order_operations": None,
        "public.appointment_configurations": None,
        "public.appointments": None,
        "public.appointment_operations": None,
        "public.integration_connections": None,
        "public.tenants": None,
        "public.audit_events": None,
        "public.outbox_jobs": "topic = 'task5.updated'",
        "public.job_attempts": "status = 'failed'",
        "public.dead_letter_jobs": "reason_code = 'task5-updated'",
        "public.secret_envelopes": None,
        "public.whatsapp_accounts": None,
        "public.whatsapp_webhook_events": None,
        "public.whatsapp_templates": "updated_at = now()",
        "public.conversations": "updated_at = now()",
        "public.messages": None,
        "public.conversation_state_events": None,
        "public.outbound_messages": "updated_at = now()",
        "public.agent_instances": None,
        "public.agent_spec_versions": None,
        "public.agent_spec_deployments": None,
        "public.knowledge_sources": None,
        "public.knowledge_source_versions": None,
        "public.structured_facts": None,
        "public.knowledge_documents": None,
        "public.knowledge_versions": None,
        "public.knowledge_version_members": None,
        "public.knowledge_ingestions": "updated_at = now()",
        "public.knowledge_ingestion_artifacts": None,
        "public.knowledge_chunks": None,
        "public.knowledge_proposals": None,
        "public.knowledge_conflicts": None,
        "public.knowledge_source_diffs": None,
        "public.knowledge_eval_evidence": None,
        "public.identity_subjects": "whatsapp_recognized_at = now()",
        "public.identity_challenges": "expires_at = expires_at + interval '1 second'",
        "public.identity_evidence": "consumed_at = now()",
        "public.actions": "state = 'IDENTITY_VERIFIED'",
        "public.action_events": None,
    }[table_name]


def _insert_parent_id(
    *,
    table_name: str,
    world: SeededWorld,
    tenant: str,
) -> UUID:
    if table_name in {
        "public.whatsapp_webhook_events",
        "public.whatsapp_templates",
        "public.conversations",
        "public.outbound_messages",
    }:
        return world.whatsapp_account_a if tenant == "a" else world.whatsapp_account_b
    if table_name in {"public.messages", "public.conversation_state_events"}:
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.conversations"]
    if table_name == "public.agent_spec_versions":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.agent_instances"]
    if table_name == "public.agent_spec_deployments":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.agent_spec_versions"]
    if table_name == "public.knowledge_source_versions":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.knowledge_sources"]
    if table_name in {"public.structured_facts", "public.knowledge_documents"}:
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.knowledge_source_versions"]
    if table_name == "public.knowledge_version_members":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.knowledge_versions"]
    if table_name == "public.knowledge_ingestions":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.knowledge_sources"]
    if table_name == "public.knowledge_ingestion_artifacts":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.knowledge_ingestions"]
    if table_name == "public.knowledge_chunks":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.knowledge_versions"]
    if table_name == "public.knowledge_proposals":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.knowledge_ingestion_artifacts"]
    if table_name == "public.knowledge_conflicts":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.knowledge_proposals"]
    if table_name == "public.knowledge_source_diffs":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.knowledge_ingestions"]
    if table_name == "public.knowledge_eval_evidence":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.knowledge_versions"]
    if table_name == "public.actions":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.conversations"]
    if table_name == "public.action_events":
        rows = world.row_a if tenant == "a" else world.row_b
        return rows["public.actions"]
    return world.insert_parent_a if tenant == "a" else world.insert_parent_b


async def assert_tenant_isolated(
    table_name: str,
    owner_column: str = "tenant_id",
    *,
    registration: TenantIsolationRegistration,
    session_factory: async_sessionmaker[AsyncSession],
    world: SeededWorld,
) -> None:
    """Exercise one registered table with the complete tenant attack contract."""

    assert registration.table_name == table_name
    assert registration.owner_column == owner_column
    own_id = world.row_a[table_name]
    foreign_id = world.row_b[table_name]
    nonexistent_id = uuid4()

    async with session_factory.begin() as session:
        await _prepare_app_session(session, world.tenant_a)
        own_visible = await session.scalar(
            text(f"SELECT count(*) FROM {table_name} WHERE id = :row_id"),
            {"row_id": own_id},
        )
        foreign_visible = await session.scalar(
            text(f"SELECT count(*) FROM {table_name} WHERE id = :row_id"),
            {"row_id": foreign_id},
        )
        absent_visible = await session.scalar(
            text(f"SELECT count(*) FROM {table_name} WHERE id = :row_id"),
            {"row_id": nonexistent_id},
        )
    assert (own_visible, foreign_visible, absent_visible) == (1, 0, 0)

    for context in (MISSING_CONTEXT, "", uuid4()):
        async with session_factory.begin() as session:
            await _prepare_app_session(session, context)
            visible_count = await session.scalar(
                text(f"SELECT count(*) FROM {table_name}")
            )
        assert visible_count == 0

    invalid_select = await _denied_fingerprint(
        session_factory,
        context="not-a-uuid",
        reset_tenant_id=world.tenant_a,
        statement=f"SELECT count(*) FROM {table_name}",
        parameters={},
    )
    assert invalid_select.sqlstate == "22P02"

    async with session_factory.begin() as session:
        await _prepare_app_session(session, world.tenant_a)
        assert await session.scalar(text(f"SELECT count(*) FROM {table_name}")) >= 1
    reset_context = await _resolve_context_after_optional_reset(
        session_factory,
        context=RESET_CONTEXT,
        reset_tenant_id=world.tenant_a,
    )
    async with session_factory.begin() as session:
        await _prepare_app_session(session, reset_context)
        assert await session.scalar(text(f"SELECT count(*) FROM {table_name}")) == 0

    matching_owner = uuid4() if table_name == "public.tenants" else world.tenant_a
    matching_parameters = _insert_parameters(
        table_name,
        tenant_id=matching_owner,
        parent_id=_insert_parent_id(table_name=table_name, world=world, tenant="a"),
        nonce=f"match-{uuid4().hex}",
    )
    if registration.insert_allowed:
        async with session_factory.begin() as session:
            await _prepare_app_session(session, matching_owner)
            result = await session.execute(
                text(f"{_insert_statement(table_name)} RETURNING id"),
                matching_parameters,
            )
        assert result.scalar_one() == matching_parameters["id"]
    else:
        matching_insert = await _denied_fingerprint(
            session_factory,
            context=matching_owner,
            reset_tenant_id=world.tenant_a,
            statement=_insert_statement(table_name),
            parameters=matching_parameters,
        )
        assert matching_insert.sqlstate == "42501"

    foreign_parameters = _insert_parameters(
        table_name,
        tenant_id=world.tenant_b,
        parent_id=_insert_parent_id(table_name=table_name, world=world, tenant="b"),
        nonce=f"foreign-{uuid4().hex}",
    )
    nonexistent_parameters = _insert_parameters(
        table_name,
        tenant_id=uuid4(),
        parent_id=uuid4(),
        nonce=f"absent-{uuid4().hex}",
    )
    foreign_insert = await _denied_fingerprint(
        session_factory,
        context=world.tenant_a,
        reset_tenant_id=world.tenant_a,
        statement=_insert_statement(table_name),
        parameters=foreign_parameters,
    )
    absent_insert = await _denied_fingerprint(
        session_factory,
        context=world.tenant_a,
        reset_tenant_id=world.tenant_a,
        statement=_insert_statement(table_name),
        parameters=nonexistent_parameters,
    )
    assert foreign_insert == absent_insert
    assert foreign_insert.sqlstate == "42501"

    for context, expected_state in (
        (MISSING_CONTEXT, "42501"),
        ("", "42501"),
        (uuid4(), "42501"),
        (RESET_CONTEXT, "42501"),
        ("not-a-uuid", "22P02" if registration.insert_allowed else "42501"),
    ):
        denial = await _denied_fingerprint(
            session_factory,
            context=context,
            reset_tenant_id=world.tenant_a,
            statement=_insert_statement(table_name),
            parameters=_insert_parameters(
                table_name,
                tenant_id=world.tenant_b,
                parent_id=_insert_parent_id(
                    table_name=table_name,
                    world=world,
                    tenant="b",
                ),
                nonce=f"context-{uuid4().hex}",
            ),
        )
        assert denial.sqlstate == expected_state

    if table_name in {
        "public.job_attempts",
        "public.dead_letter_jobs",
        "public.whatsapp_webhook_events",
        "public.whatsapp_templates",
        "public.conversations",
        "public.messages",
        "public.conversation_state_events",
        "public.actions",
        "public.action_events",
    }:
        foreign_parent_parameters = _insert_parameters(
            table_name,
            tenant_id=world.tenant_a,
            parent_id=_insert_parent_id(
                table_name=table_name,
                world=world,
                tenant="b",
            ),
            nonce=f"foreign-parent-{uuid4().hex}",
        )
        absent_parent_parameters = _insert_parameters(
            table_name,
            tenant_id=world.tenant_a,
            parent_id=uuid4(),
            nonce=f"absent-parent-{uuid4().hex}",
        )
        foreign_parent_denial = await _denied_fingerprint(
            session_factory,
            context=world.tenant_a,
            reset_tenant_id=world.tenant_a,
            statement=_insert_statement(table_name),
            parameters=foreign_parent_parameters,
        )
        absent_parent_denial = await _denied_fingerprint(
            session_factory,
            context=world.tenant_a,
            reset_tenant_id=world.tenant_a,
            statement=_insert_statement(table_name),
            parameters=absent_parent_parameters,
        )
        assert foreign_parent_denial == absent_parent_denial
        assert foreign_parent_denial.sqlstate == "23503"

    update_assignment = _matching_update(table_name)
    update_statement = (
        f"UPDATE {table_name} SET {update_assignment or f'{owner_column} = :owner'} "
        "WHERE id = :row_id RETURNING id"
    )
    if registration.update_allowed:
        assert update_assignment is not None
        assert await _returning_ids(
            session_factory,
            context=world.tenant_a,
            reset_tenant_id=world.tenant_a,
            statement=update_statement,
            parameters={"row_id": own_id},
        ) == [own_id]
        for row_id in (foreign_id, nonexistent_id):
            assert (
                await _returning_ids(
                    session_factory,
                    context=world.tenant_a,
                    reset_tenant_id=world.tenant_a,
                    statement=update_statement,
                    parameters={"row_id": row_id},
                )
                == []
            )
        for context in (MISSING_CONTEXT, "", uuid4(), RESET_CONTEXT):
            assert (
                await _returning_ids(
                    session_factory,
                    context=context,
                    reset_tenant_id=world.tenant_a,
                    statement=update_statement,
                    parameters={"row_id": own_id},
                )
                == []
            )
        invalid_update = await _denied_fingerprint(
            session_factory,
            context="not-a-uuid",
            reset_tenant_id=world.tenant_a,
            statement=update_statement,
            parameters={"row_id": own_id},
        )
        assert invalid_update.sqlstate == "22P02"
    else:
        update_denials = [
            await _denied_fingerprint(
                session_factory,
                context=context,
                reset_tenant_id=world.tenant_a,
                statement=update_statement,
                parameters={"owner": world.tenant_a, "row_id": row_id},
            )
            for context in (
                world.tenant_a,
                MISSING_CONTEXT,
                "",
                "not-a-uuid",
                uuid4(),
                RESET_CONTEXT,
            )
            for row_id in (own_id, foreign_id, nonexistent_id)
        ]
        assert all(denial == update_denials[0] for denial in update_denials)
        assert update_denials[0].sqlstate == "42501"

    reassignment = await _denied_fingerprint(
        session_factory,
        context=world.tenant_a,
        reset_tenant_id=world.tenant_a,
        statement=(
            f"UPDATE {table_name} SET {owner_column} = :owner WHERE id = :row_id"
        ),
        parameters={"owner": world.tenant_b, "row_id": own_id},
    )
    assert reassignment.sqlstate in registration.reassignment_denials

    delete_statement = f"DELETE FROM {table_name} WHERE id = :row_id RETURNING id"
    if registration.delete_allowed:
        for row_id in (foreign_id, nonexistent_id):
            assert (
                await _returning_ids(
                    session_factory,
                    context=world.tenant_a,
                    reset_tenant_id=world.tenant_a,
                    statement=delete_statement,
                    parameters={"row_id": row_id},
                )
                == []
            )
        for context in (MISSING_CONTEXT, "", uuid4(), RESET_CONTEXT):
            assert (
                await _returning_ids(
                    session_factory,
                    context=context,
                    reset_tenant_id=world.tenant_a,
                    statement=delete_statement,
                    parameters={"row_id": own_id},
                )
                == []
            )
        invalid_delete = await _denied_fingerprint(
            session_factory,
            context="not-a-uuid",
            reset_tenant_id=world.tenant_a,
            statement=delete_statement,
            parameters={"row_id": own_id},
        )
        assert invalid_delete.sqlstate == "22P02"
        assert await _returning_ids(
            session_factory,
            context=world.tenant_a,
            reset_tenant_id=world.tenant_a,
            statement=delete_statement,
            parameters={"row_id": own_id},
        ) == [own_id]
    else:
        delete_denials = [
            await _denied_fingerprint(
                session_factory,
                context=context,
                reset_tenant_id=world.tenant_a,
                statement=delete_statement,
                parameters={"row_id": row_id},
            )
            for context in (
                world.tenant_a,
                MISSING_CONTEXT,
                "",
                "not-a-uuid",
                uuid4(),
                RESET_CONTEXT,
            )
            for row_id in (own_id, foreign_id, nonexistent_id)
        ]
        assert all(denial == delete_denials[0] for denial in delete_denials)
        assert delete_denials[0].sqlstate == "42501"

    async with session_factory.begin() as session:
        own_survives = await session.scalar(
            text(f"SELECT count(*) FROM {table_name} WHERE id = :row_id"),
            {"row_id": own_id},
        )
        foreign_survives = await session.scalar(
            text(f"SELECT count(*) FROM {table_name} WHERE id = :row_id"),
            {"row_id": foreign_id},
        )
    assert (own_survives, foreign_survives) == (
        0 if registration.delete_allowed else 1,
        1,
    )


@pytest.mark.asyncio
async def test_every_public_tenant_owned_table_is_registered(
    database_engine: AsyncEngine,
) -> None:
    async with database_engine.connect() as connection:
        tenant_owned = await _discover_tenant_owned_tables(connection)

    registered = {
        (registration.table_name, registration.owner_column)
        for registration in TENANT_ISOLATION_REGISTRY
    }
    assert registered == tenant_owned


@pytest.mark.asyncio
async def test_catalog_excludes_security_invoker_views_and_detects_base_tables(
    database_engine: AsyncEngine,
) -> None:
    registered = {
        (registration.table_name, registration.owner_column)
        for registration in TENANT_ISOLATION_REGISTRY
    }
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE VIEW public.task5_tenant_projection "
                "WITH (security_invoker = true) AS "
                "SELECT tenant_id FROM public.audit_events"
            )
        )
        with_view = await _discover_tenant_owned_tables(connection)
        await connection.execute(
            text(
                "CREATE TABLE public.task5_unregistered_tenant_data "
                "(id uuid PRIMARY KEY, tenant_id uuid NOT NULL)"
            )
        )
        with_base_table = await _discover_tenant_owned_tables(connection)
        await connection.execute(text("DROP VIEW public.task5_tenant_projection"))
        await connection.execute(
            text("DROP TABLE public.task5_unregistered_tenant_data")
        )

    assert with_view == registered
    assert with_base_table - registered == {
        ("public.task5_unregistered_tenant_data", "tenant_id")
    }


@pytest.mark.parametrize(
    "registration",
    TENANT_ISOLATION_REGISTRY,
    ids=lambda registration: registration.table_name,
)
@pytest.mark.asyncio
async def test_registered_table_passes_the_reusable_attack_matrix(
    registration: TenantIsolationRegistration,
    session_factory: async_sessionmaker[AsyncSession],
    seeded_world: SeededWorld,
) -> None:
    await assert_tenant_isolated(
        registration.table_name,
        registration.owner_column,
        registration=registration,
        session_factory=session_factory,
        world=seeded_world,
    )


class AllowingVerifier:
    def __init__(self, principal: AdminPrincipal) -> None:
        self._principal = principal

    async def verify(self, access_jwt: str) -> AdminPrincipal:
        assert access_jwt == "signed-platform-admin"
        return self._principal


class DenyingVerifier:
    async def verify(self, access_jwt: str) -> AdminPrincipal:
        assert access_jwt == "signed-without-platform-role"
        raise DomainError(
            type="https://agents-factory.dev/problems/platform-admin-required",
            title="Platform Admin Required",
            status=403,
            detail="Platform administrator access is required.",
            code="platform_admin_required",
        )


@pytest.mark.asyncio
async def test_cross_tenant_admin_read_requires_claim_and_database_membership(
    database_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    seeded_world: SeededWorld,
) -> None:
    principal = AdminPrincipal(user_id=uuid4(), session_id=uuid4())
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO auth.users "
                "(id, aud, role, email, encrypted_password, created_at, updated_at) "
                "VALUES (:user_id, 'authenticated', 'authenticated', :email, '', "
                "now(), now())"
            ),
            {
                "user_id": principal.user_id,
                "email": f"task5-{principal.user_id}@example.test",
            },
        )

    with pytest.raises(DomainError) as claim_only:
        async with session_factory.begin() as session:
            await PlatformAdminAuthorizer(AllowingVerifier(principal)).authorize(
                authorization="Bearer signed-platform-admin",
                session=session,
            )
    claim_only_problem = (
        claim_only.value.type,
        claim_only.value.title,
        claim_only.value.status,
        claim_only.value.detail,
        claim_only.value.code,
    )
    assert claim_only_problem == (
        "https://agents-factory.dev/problems/platform-admin-required",
        "Platform Admin Required",
        403,
        "Platform administrator access is required.",
        "platform_admin_required",
    )

    async with database_engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO public.platform_admins (user_id) VALUES (:user_id)"),
            {"user_id": principal.user_id},
        )

    with pytest.raises(DomainError) as table_only:
        async with session_factory.begin() as session:
            await PlatformAdminAuthorizer(DenyingVerifier()).authorize(
                authorization="Bearer signed-without-platform-role",
                session=session,
            )
    table_only_problem = (
        table_only.value.type,
        table_only.value.title,
        table_only.value.status,
        table_only.value.detail,
        table_only.value.code,
    )
    assert table_only_problem == claim_only_problem

    async with session_factory.begin() as session:
        authorized = await PlatformAdminAuthorizer(
            AllowingVerifier(principal)
        ).authorize(
            authorization="Bearer signed-platform-admin",
            session=session,
        )
        visible = await TenantRepository(session).list_visible()

    assert authorized == principal
    assert {tenant.id for tenant in visible} == {
        seeded_world.tenant_a,
        seeded_world.tenant_b,
    }
