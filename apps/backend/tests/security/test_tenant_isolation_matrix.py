from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agents_factory.common.errors import DomainError
from agents_factory.common.security import AdminPrincipal, PlatformAdminAuthorizer
from agents_factory.modules.tenants.repository import TenantRepository


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
RUNNER = REPOSITORY_ROOT / "infrastructure/scripts/run_tenant_isolation.py"
LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})
MISSING_CONTEXT: Final = object()


@dataclass(frozen=True, slots=True)
class TenantIsolationRegistration:
    table_name: str
    owner_column: str = "tenant_id"
    insert_allowed: bool = True
    update_allowed: bool = True


TENANT_ISOLATION_REGISTRY = (
    TenantIsolationRegistration(
        "public.tenants",
        "id",
        insert_allowed=False,
        update_allowed=False,
    ),
    TenantIsolationRegistration(
        "public.audit_events",
        insert_allowed=True,
        update_allowed=False,
    ),
    TenantIsolationRegistration("public.outbox_jobs"),
    TenantIsolationRegistration("public.job_attempts"),
    TenantIsolationRegistration("public.dead_letter_jobs"),
)


@dataclass(frozen=True, slots=True)
class SeededWorld:
    tenant_a: UUID
    tenant_b: UUID
    row_a: dict[str, UUID]
    row_b: dict[str, UUID]
    insert_parent_a: UUID
    insert_parent_b: UUID


@pytest.fixture(scope="session")
def local_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail("TEST_DATABASE_URL must be supplied by the local matrix runner")
    parsed = urlsplit(database_url)
    if parsed.scheme != "postgresql+asyncpg" or parsed.hostname not in LOOPBACK_HOSTS:
        pytest.fail("tenant isolation tests require loopback PostgreSQL")
    if (REPOSITORY_ROOT / "supabase/.temp/project-ref").exists():
        pytest.fail("linked Supabase projects are forbidden for tenant isolation tests")
    return database_url


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
                "TRUNCATE TABLE public.dead_letter_jobs, public.job_attempts, "
                "public.outbox_jobs, public.audit_events, public.platform_admins, "
                "public.tenants CASCADE"
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

    world = SeededWorld(
        tenant_a=tenant_a,
        tenant_b=tenant_b,
        row_a=row_a,
        row_b=row_b,
        insert_parent_a=insert_parent_a,
        insert_parent_b=insert_parent_b,
    )
    try:
        yield world
    finally:
        await _clear_foundation_data(database_engine)


async def _prepare_app_session(session: AsyncSession, context: object) -> None:
    await session.execute(text("SET LOCAL ROLE agents_factory_app"))
    if context is not MISSING_CONTEXT:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(context)},
        )


def _sqlstate(error: DBAPIError) -> str:
    sqlstate = getattr(error.orig, "sqlstate", None)
    assert isinstance(sqlstate, str)
    return sqlstate


async def _denied_sqlstate(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    context: object,
    statement: str,
    parameters: dict[str, object],
) -> str:
    with pytest.raises(DBAPIError) as caught:
        async with session_factory.begin() as session:
            await _prepare_app_session(session, context)
            await session.execute(text(statement), parameters)
    return _sqlstate(caught.value)


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
    }


def _matching_update(table_name: str) -> str | None:
    return {
        "public.tenants": None,
        "public.audit_events": None,
        "public.outbox_jobs": "topic = 'task5.updated'",
        "public.job_attempts": "status = 'failed'",
        "public.dead_letter_jobs": "reason_code = 'task5-updated'",
    }[table_name]


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

    invalid_select_state = await _denied_sqlstate(
        session_factory,
        context="not-a-uuid",
        statement=f"SELECT count(*) FROM {table_name}",
        parameters={},
    )
    assert invalid_select_state == "22P02"

    async with session_factory.begin() as session:
        await _prepare_app_session(session, world.tenant_a)
        assert await session.scalar(text(f"SELECT count(*) FROM {table_name}")) >= 1
    async with session_factory.begin() as session:
        await _prepare_app_session(session, MISSING_CONTEXT)
        assert await session.scalar(text(f"SELECT count(*) FROM {table_name}")) == 0

    matching_owner = uuid4() if table_name == "public.tenants" else world.tenant_a
    matching_parameters = _insert_parameters(
        table_name,
        tenant_id=matching_owner,
        parent_id=world.insert_parent_a,
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
        matching_insert_state = await _denied_sqlstate(
            session_factory,
            context=matching_owner,
            statement=_insert_statement(table_name),
            parameters=matching_parameters,
        )
        assert matching_insert_state == "42501"

    foreign_parameters = _insert_parameters(
        table_name,
        tenant_id=world.tenant_b,
        parent_id=world.insert_parent_b,
        nonce=f"foreign-{uuid4().hex}",
    )
    nonexistent_parameters = _insert_parameters(
        table_name,
        tenant_id=uuid4(),
        parent_id=uuid4(),
        nonce=f"absent-{uuid4().hex}",
    )
    foreign_insert_state = await _denied_sqlstate(
        session_factory,
        context=world.tenant_a,
        statement=_insert_statement(table_name),
        parameters=foreign_parameters,
    )
    absent_insert_state = await _denied_sqlstate(
        session_factory,
        context=world.tenant_a,
        statement=_insert_statement(table_name),
        parameters=nonexistent_parameters,
    )
    assert foreign_insert_state == absent_insert_state == "42501"

    for context, expected_state in (
        (MISSING_CONTEXT, "42501"),
        ("", "42501"),
        (uuid4(), "42501"),
        ("not-a-uuid", "22P02" if registration.insert_allowed else "42501"),
    ):
        state = await _denied_sqlstate(
            session_factory,
            context=context,
            statement=_insert_statement(table_name),
            parameters=_insert_parameters(
                table_name,
                tenant_id=world.tenant_b,
                parent_id=world.insert_parent_b,
                nonce=f"context-{uuid4().hex}",
            ),
        )
        assert state == expected_state

    update_assignment = _matching_update(table_name)
    if registration.update_allowed:
        assert update_assignment is not None
        async with session_factory.begin() as session:
            await _prepare_app_session(session, world.tenant_a)
            result = await session.execute(
                text(
                    f"UPDATE {table_name} SET {update_assignment} "
                    "WHERE id = :row_id RETURNING id"
                ),
                {"row_id": own_id},
            )
        assert result.scalar_one() == own_id
        async with session_factory.begin() as session:
            await _prepare_app_session(session, world.tenant_a)
            foreign_result = await session.execute(
                text(
                    f"UPDATE {table_name} SET {update_assignment} "
                    "WHERE id = :row_id RETURNING id"
                ),
                {"row_id": foreign_id},
            )
            absent_result = await session.execute(
                text(
                    f"UPDATE {table_name} SET {update_assignment} "
                    "WHERE id = :row_id RETURNING id"
                ),
                {"row_id": nonexistent_id},
            )
        assert (
            foreign_result.scalar_one_or_none(),
            absent_result.scalar_one_or_none(),
        ) == (None, None)
    else:
        own_update_state = await _denied_sqlstate(
            session_factory,
            context=world.tenant_a,
            statement=f"UPDATE {table_name} SET {owner_column} = :owner WHERE id = :row_id",
            parameters={"owner": world.tenant_a, "row_id": own_id},
        )
        foreign_update_state = await _denied_sqlstate(
            session_factory,
            context=world.tenant_a,
            statement=f"UPDATE {table_name} SET {owner_column} = :owner WHERE id = :row_id",
            parameters={"owner": world.tenant_a, "row_id": foreign_id},
        )
        assert own_update_state == foreign_update_state == "42501"

    reassignment_state = await _denied_sqlstate(
        session_factory,
        context=world.tenant_a,
        statement=f"UPDATE {table_name} SET {owner_column} = :owner WHERE id = :row_id",
        parameters={"owner": world.tenant_b, "row_id": own_id},
    )
    assert reassignment_state == "42501"

    delete_states = []
    for row_id in (own_id, foreign_id, nonexistent_id):
        delete_states.append(
            await _denied_sqlstate(
                session_factory,
                context=world.tenant_a,
                statement=f"DELETE FROM {table_name} WHERE id = :row_id",
                parameters={"row_id": row_id},
            )
        )
    assert delete_states == ["42501", "42501", "42501"]

    async with session_factory.begin() as session:
        own_survives = await session.scalar(
            text(f"SELECT count(*) FROM {table_name} WHERE id = :row_id"),
            {"row_id": own_id},
        )
        foreign_survives = await session.scalar(
            text(f"SELECT count(*) FROM {table_name} WHERE id = :row_id"),
            {"row_id": foreign_id},
        )
    assert (own_survives, foreign_survives) == (1, 1)


@pytest.mark.asyncio
async def test_every_public_tenant_owned_table_is_registered(
    database_engine: AsyncEngine,
) -> None:
    async with database_engine.connect() as connection:
        tenant_owned = (
            await connection.execute(
                text(
                    "SELECT format('%I.%I', table_schema, table_name), column_name "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND (column_name = 'tenant_id' "
                    "OR (table_name = 'tenants' AND column_name = 'id')) "
                    "ORDER BY table_name"
                )
            )
        ).all()

    registered = {
        (registration.table_name, registration.owner_column)
        for registration in TENANT_ISOLATION_REGISTRY
    }
    assert registered == set(tenant_owned)


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
    assert (claim_only.value.status, claim_only.value.code) == (
        403,
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
    assert (table_only.value.status, table_only.value.code) == (
        403,
        "platform_admin_required",
    )

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


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


@pytest.mark.parametrize(
    ("python_exit", "pgtap_exit", "expected_exit", "expected_command"),
    (
        (
            19,
            0,
            19,
            "uv run --all-packages pytest "
            "apps/backend/tests/security/test_tenant_isolation_matrix.py",
        ),
        (
            0,
            23,
            23,
            "pnpm supabase test db --local supabase/tests/rls_matrix_test.sql",
        ),
    ),
)
def test_focused_runner_propagates_a_red_matrix(
    tmp_path: Path,
    python_exit: int,
    pgtap_exit: int,
    expected_exit: int,
    expected_command: str,
) -> None:
    command_log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "uv",
        "#!/bin/sh\n"
        'printf "uv %s\\n" "$*" >> "$TASK5_COMMAND_LOG"\n'
        'exit "$TASK5_PYTHON_EXIT"\n',
    )
    _write_executable(
        fake_bin / "pnpm",
        "#!/bin/sh\n"
        'printf "pnpm %s\\n" "$*" >> "$TASK5_COMMAND_LOG"\n'
        'if test "$1 $2 $3 $4" = "supabase status -o json"; then\n'
        "  printf '%s\\n' "
        '\'{"DB_URL":"postgresql://local@127.0.0.1:54322/postgres"}\'\n'
        "  exit 0\n"
        "fi\n"
        'if test "$1 $2 $3" = "supabase test db"; then\n'
        '  exit "$TASK5_PGTAP_EXIT"\n'
        "fi\n"
        "exit 1\n",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "TASK5_COMMAND_LOG": str(command_log),
            "TASK5_PYTHON_EXIT": str(python_exit),
            "TASK5_PGTAP_EXIT": str(pgtap_exit),
        }
    )

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--database-ready"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_exit
    assert expected_command in command_log.read_text()


def test_security_aggregate_cannot_skip_the_focused_runner(tmp_path: Path) -> None:
    command_log = tmp_path / "aggregate.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "git", "#!/bin/sh\nexit 1\n")
    for command in ("sh", "uv", "pnpm"):
        _write_executable(fake_bin / command, "#!/bin/sh\nexit 0\n")
    _write_executable(
        fake_bin / "python3",
        '#!/bin/sh\nprintf "python3 %s\\n" "$*" >> "$TASK5_COMMAND_LOG"\nexit 29\n',
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "TASK5_COMMAND_LOG": str(command_log),
        }
    )

    result = subprocess.run(
        [
            "/bin/sh",
            str(
                REPOSITORY_ROOT / "infrastructure/scripts/check_repository_security.sh"
            ),
            str(REPOSITORY_ROOT / ".github/workflows/ci.yml"),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 29, result.stderr
    assert (
        "python3 infrastructure/scripts/run_tenant_isolation.py --database-ready"
        in command_log.read_text()
    )
