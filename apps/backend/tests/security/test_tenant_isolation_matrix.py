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


TENANT_ISOLATION_REGISTRY = (
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
                "TRUNCATE TABLE public.agent_spec_deployments, "
                "public.agent_spec_versions, public.agent_instances, "
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
                    "'knowledge', jsonb_build_object('digest', :digest), "
                    "'code_digest', :digest))"
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
        "message_id": f"task5-message-{nonce}",
        "provider_template_id": f"task5-template-{nonce}",
        "template_name": f"task5_{nonce[:80]}",
        "idempotency_key": f"task5-outbound-{nonce}",
        "arrival_sequence": uuid4().int % 1_000_000_000 + 2,
        "version": uuid4().int % 1_000_000_000 + 2,
        "parent_id": parent_id,
        "digest": "a" * 64,
    }


def _matching_update(table_name: str) -> str | None:
    return {
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
    assert reassignment.sqlstate == "42501"

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
