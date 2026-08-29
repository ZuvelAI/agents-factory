from __future__ import annotations

import base64
import os
import sys
import tomllib
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

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

from agents_factory.common.context import TenantContext
from agents_factory.modules.secrets.contracts import SecretAccessDenied, SecretRef
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.secrets.repository import SecretVault


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT / "infrastructure/scripts"))

from local_database_url import (  # noqa: E402
    LocalDatabaseUrlError,
    validate_test_database_url,
)


EXPECTED_DATABASE = "postgres"
PLAINTEXT = b"database-dump-must-never-contain-this-secret"
PURPOSE = "connector.authorization"
RECORD_CONTEXT = "connection:task5a-database"


def _context(tenant_id: UUID, *, actor_id: UUID | None = None) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=uuid4() if actor_id is None else actor_id,
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )


def _problem(error: SecretAccessDenied) -> tuple[object, ...]:
    return (
        error.type,
        error.title,
        error.status,
        error.detail,
        error.code,
    )


async def _truncate_secret_test_data(connection: AsyncConnection) -> None:
    for statement in (
        "ALTER TABLE public.audit_events DISABLE TRIGGER audit_events_reject_truncate",
        "ALTER TABLE public.agent_spec_deployments "
        "DISABLE TRIGGER agent_spec_deployments_append_only",
        "ALTER TABLE public.action_events DISABLE TRIGGER action_events_append_only",
        "ALTER TABLE public.knowledge_source_versions "
        "DISABLE TRIGGER knowledge_source_versions_append_only",
        "ALTER TABLE public.structured_facts "
        "DISABLE TRIGGER structured_facts_append_only",
        "ALTER TABLE public.knowledge_documents "
        "DISABLE TRIGGER knowledge_documents_append_only",
        "ALTER TABLE public.knowledge_version_members "
        "DISABLE TRIGGER knowledge_version_members_append_only",
        "ALTER TABLE public.knowledge_ingestion_artifacts "
        "DISABLE TRIGGER knowledge_ingestion_artifacts_append_only",
        "ALTER TABLE public.knowledge_chunks "
        "DISABLE TRIGGER knowledge_chunks_append_only",
    ):
        await connection.execute(text(statement))
    await connection.execute(
        text(
            "TRUNCATE TABLE public.secret_envelopes, public.audit_events, "
            "public.tenants CASCADE"
        )
    )
    for statement in (
        "ALTER TABLE public.knowledge_chunks "
        "ENABLE TRIGGER knowledge_chunks_append_only",
        "ALTER TABLE public.knowledge_ingestion_artifacts "
        "ENABLE TRIGGER knowledge_ingestion_artifacts_append_only",
        "ALTER TABLE public.knowledge_version_members "
        "ENABLE TRIGGER knowledge_version_members_append_only",
        "ALTER TABLE public.knowledge_documents "
        "ENABLE TRIGGER knowledge_documents_append_only",
        "ALTER TABLE public.structured_facts "
        "ENABLE TRIGGER structured_facts_append_only",
        "ALTER TABLE public.knowledge_source_versions "
        "ENABLE TRIGGER knowledge_source_versions_append_only",
        "ALTER TABLE public.action_events ENABLE TRIGGER action_events_append_only",
        "ALTER TABLE public.agent_spec_deployments "
        "ENABLE TRIGGER agent_spec_deployments_append_only",
        "ALTER TABLE public.audit_events ENABLE TRIGGER audit_events_reject_truncate",
    ):
        await connection.execute(text(statement))


@pytest.fixture(scope="session")
def local_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail("TEST_DATABASE_URL must be supplied by the local matrix runner")
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
        pytest.fail("secret tests require canonical local Supabase PostgreSQL")


@pytest_asyncio.fixture
async def database_engine(local_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(local_database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "GRANT agents_factory_app TO CURRENT_USER WITH INHERIT FALSE, SET TRUE"
            )
        )
        await _truncate_secret_test_data(connection)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await _truncate_secret_test_data(connection)
            await connection.execute(
                text("REVOKE agents_factory_app FROM CURRENT_USER")
            )
        await engine.dispose()


@pytest.fixture
def session_factory(
    database_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(database_engine, expire_on_commit=False)


async def _vault_call(
    session_factory: async_sessionmaker[AsyncSession],
    provider: EnvironmentMasterKeyProvider,
    method: str,
    **arguments: object,
) -> object:
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        vault = SecretVault.for_session(session, key_provider=provider)
        operation = getattr(vault, method)
        return await operation(**arguments)


@pytest.mark.asyncio
async def test_vault_database_is_ciphertext_only_tenant_bound_and_audited(
    database_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    context_a = _context(tenant_a)
    context_b = _context(tenant_b)
    unauthenticated_a = TenantContext(
        tenant_id=tenant_a,
        actor_id=None,
        actor_type="system",
        correlation_id=uuid4(),
    )
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES "
                "(:tenant_a, 'task5a-a', 'Task 5A A'), "
                "(:tenant_b, 'task5a-b', 'Task 5A B')"
            ),
            {"tenant_a": tenant_a, "tenant_b": tenant_b},
        )

    provider = EnvironmentMasterKeyProvider()
    first_ref = await _vault_call(
        session_factory,
        provider,
        "store",
        context=context_a,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        plaintext=PLAINTEXT,
    )
    second_ref = await _vault_call(
        session_factory,
        provider,
        "store",
        context=context_a,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        plaintext=PLAINTEXT,
    )
    assert isinstance(first_ref, SecretRef)
    assert isinstance(second_ref, SecretRef)

    resolved = await _vault_call(
        session_factory,
        provider,
        "load",
        context=context_a,
        reference=first_ref,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
    )
    assert isinstance(resolved, ResolvedSecret)
    assert resolved.reveal() == PLAINTEXT
    assert repr(resolved) == "[REDACTED]"

    wrong_key = base64.urlsafe_b64encode(b"w" * 32).rstrip(b"=").decode()
    wrong_provider = EnvironmentMasterKeyProvider(
        environment={"APP_MASTER_KEY": wrong_key}
    )
    missing_ref = SecretRef(uuid4())
    attempts = (
        (provider, context_b, first_ref, PURPOSE, RECORD_CONTEXT),
        (provider, context_a, first_ref, "wrong-purpose", RECORD_CONTEXT),
        (provider, context_a, first_ref, PURPOSE, "wrong-context"),
        (provider, unauthenticated_a, first_ref, PURPOSE, RECORD_CONTEXT),
        (provider, context_a, missing_ref, PURPOSE, RECORD_CONTEXT),
        (wrong_provider, context_a, first_ref, PURPOSE, RECORD_CONTEXT),
    )
    problems: list[tuple[object, ...]] = []
    for attempt_provider, context, reference, purpose, record_context in attempts:
        with pytest.raises(SecretAccessDenied) as denied:
            await _vault_call(
                session_factory,
                attempt_provider,
                "load",
                context=context,
                reference=reference,
                purpose=purpose,
                record_context=record_context,
            )
        problems.append(_problem(denied.value))
    assert all(problem == problems[0] for problem in problems)

    async with database_engine.connect() as connection:
        rows = (
            (
                await connection.execute(
                    text(
                        "SELECT id, ciphertext, wrapped_data_key, payload_nonce, "
                        "key_nonce, algorithm, format_version, key_id, key_version "
                        "FROM public.secret_envelopes ORDER BY id"
                    )
                )
            )
            .mappings()
            .all()
        )
        dump = await connection.scalar(
            text(
                "SELECT coalesce(jsonb_agg(to_jsonb(secret_envelopes)), '[]')::text "
                "FROM public.secret_envelopes"
            )
        )
        audits = (
            await connection.execute(
                text(
                    "SELECT tenant_id, event_type, payload::text "
                    "FROM public.audit_events "
                    "WHERE event_type LIKE 'secret.%' ORDER BY occurred_at, id"
                )
            )
        ).all()

    assert len(rows) == 2
    assert rows[0]["ciphertext"] != rows[1]["ciphertext"]
    assert rows[0]["payload_nonce"] != rows[1]["payload_nonce"]
    assert rows[0]["key_nonce"] != rows[1]["key_nonce"]
    assert all(len(row["payload_nonce"]) == len(row["key_nonce"]) == 12 for row in rows)
    assert all(len(row["wrapped_data_key"]) == 48 for row in rows)
    assert all(
        (row["algorithm"], row["format_version"], row["key_id"], row["key_version"])
        == ("AES-256-GCM", 1, "environment-master-key", 1)
        for row in rows
    )
    serialized_evidence = f"{dump}\n{audits}\n{problems}"
    assert PLAINTEXT.decode() not in serialized_evidence
    assert os.environ["APP_MASTER_KEY"] not in serialized_evidence
    for forbidden_field in (
        "plaintext",
        "master_key",
        "wrapped_data_key",
        "payload_nonce",
        "key_nonce",
    ):
        assert forbidden_field not in "\n".join(str(row[2]) for row in audits)
    assert sum(event_type == "secret.access_denied" for _, event_type, _ in audits) == 6

    await _vault_call(
        session_factory,
        provider,
        "delete",
        context=context_a,
        reference=first_ref,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
    )
    async with database_engine.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT count(*) FROM public.secret_envelopes WHERE id = :id"),
                {"id": first_ref.id},
            )
            == 0
        )
