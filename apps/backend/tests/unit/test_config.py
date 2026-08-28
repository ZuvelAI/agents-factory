from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import cast
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.config import (
    REQUIRED_ENVIRONMENT_VARIABLES,
    ConfigurationError,
    load_settings,
)
from agents_factory.database import transaction


def _valid_environment() -> dict[str, str]:
    return {
        "ENVIRONMENT": "test",
        "LOG_LEVEL": "info",
        "DATABASE_URL": "postgresql+asyncpg://app:database-secret@database/app",
        "REDIS_URL": "redis://:redis-secret@redis:6379/0",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "publishable-secret-sentinel",
        "SUPABASE_JWT_ISSUER": "https://example.supabase.co/auth/v1",
        "SUPABASE_JWT_AUDIENCE": "authenticated",
        "APP_MASTER_KEY": "master-secret-sentinel",
        "META_APP_SECRET": "meta-app-secret-sentinel",
        "META_WEBHOOK_VERIFY_TOKEN": "meta-verify-token-sentinel",
    }


def test_load_settings_reports_all_missing_variable_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in REQUIRED_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ConfigurationError) as captured:
        load_settings()

    assert captured.value.missing_variables == REQUIRED_ENVIRONMENT_VARIABLES
    assert captured.value.invalid_variables == ()
    for name in REQUIRED_ENVIRONMENT_VARIABLES:
        if "SECRET" not in name:
            assert name in str(captured.value)
    assert "META_APP_SECRET" not in str(captured.value)
    assert "META_APP_CREDENTIAL" in str(captured.value)


def test_load_settings_never_exposes_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _valid_environment()
    environment["ENVIRONMENT"] = "invalid-environment-secret-sentinel"
    environment["LOG_LEVEL"] = "invalid-log-level-secret-sentinel"
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError) as captured:
        load_settings()

    message = str(captured.value)
    assert captured.value.invalid_variables == ("ENVIRONMENT", "LOG_LEVEL")
    assert "invalid-environment-secret-sentinel" not in message
    assert "invalid-log-level-secret-sentinel" not in message
    assert "database-secret" not in message
    assert "redis-secret" not in message
    assert "master-secret-sentinel" not in message


@pytest.mark.parametrize(
    ("variable", "invalid_value"),
    [
        ("DATABASE_URL", "invalid-database-url-secret-sentinel"),
        (
            "DATABASE_URL",
            "postgresql+asyncpg://app:secret@database:notaport/app",
        ),
        ("DATABASE_URL", "postgresql+asyncpg://app:secret@database:0/app"),
        ("DATABASE_URL", "postgresql+asyncpg://app:secret@database:/app"),
        ("DATABASE_URL", "postgresql+asyncpg://app:secret@database:65536/app"),
        ("DATABASE_URL", "postgresql+asyncpg://app:secret@data base/app"),
        ("DATABASE_URL", "postgresql+asyncpg://app:secret@-database/app"),
        ("REDIS_URL", "invalid-redis-url-secret-sentinel"),
        ("REDIS_URL", "redis://redis:notaport/0"),
        ("REDIS_URL", "redis://redis:0/0"),
        ("REDIS_URL", "redis://redis:/0"),
        ("REDIS_URL", "redis://redis:65536/0"),
        ("REDIS_URL", "redis://redis host/0"),
        ("REDIS_URL", "redis://redis_/0"),
        ("SUPABASE_URL", "http://invalid-supabase-url-secret-sentinel"),
        ("SUPABASE_URL", "https://example.supabase.co:notaport"),
        ("SUPABASE_JWT_ISSUER", "invalid-jwt-issuer-secret-sentinel"),
    ],
)
def test_load_settings_rejects_malformed_urls_without_exposing_them(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    invalid_value: str,
) -> None:
    environment = _valid_environment()
    environment[variable] = invalid_value
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError) as captured:
        load_settings()

    assert captured.value.invalid_variables == (variable,)
    assert invalid_value not in str(captured.value)


def test_load_settings_accepts_dependency_urls_without_explicit_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _valid_environment()
    environment["DATABASE_URL"] = "postgresql+asyncpg://app:secret@database/app"
    environment["REDIS_URL"] = "redis://redis/0"
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    settings = load_settings()

    assert settings.database_url.get_secret_value() == environment["DATABASE_URL"]
    assert settings.redis_url.get_secret_value() == environment["REDIS_URL"]


@pytest.mark.parametrize("environment_name", ["staging", "production"])
@pytest.mark.parametrize(
    ("variable", "insecure_value"),
    [
        ("SUPABASE_URL", "http://127.0.0.1:54321"),
        ("SUPABASE_JWT_ISSUER", "http://localhost:54321/auth/v1"),
    ],
)
def test_production_like_environments_reject_loopback_http(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    variable: str,
    insecure_value: str,
) -> None:
    environment = _valid_environment()
    environment["ENVIRONMENT"] = environment_name
    environment[variable] = insecure_value
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError) as captured:
        load_settings()

    assert captured.value.invalid_variables == (variable,)
    assert insecure_value not in str(captured.value)


@pytest.mark.parametrize("environment_name", ["development", "test"])
def test_local_environments_allow_loopback_http_for_supabase_urls(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
) -> None:
    environment = _valid_environment()
    environment["ENVIRONMENT"] = environment_name
    environment["SUPABASE_URL"] = "http://127.0.0.1:54321"
    environment["SUPABASE_JWT_ISSUER"] = "http://localhost:54321/auth/v1"
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    settings = load_settings()

    assert settings.supabase_url == environment["SUPABASE_URL"]
    assert settings.supabase_jwt_issuer == environment["SUPABASE_JWT_ISSUER"]


def test_settings_keep_credential_bearing_values_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in _valid_environment().items():
        monkeypatch.setenv(name, value)

    settings = load_settings()

    assert isinstance(settings.database_url, SecretStr)
    assert isinstance(settings.redis_url, SecretStr)
    assert isinstance(settings.supabase_publishable_key, SecretStr)
    assert isinstance(settings.app_master_key, SecretStr)
    assert isinstance(settings.meta_app_secret, SecretStr)
    assert isinstance(settings.meta_webhook_verify_token, SecretStr)
    serialized = settings.model_dump(mode="json")
    assert serialized["database_url"] == "**********"
    assert serialized["redis_url"] == "**********"
    assert serialized["supabase_publishable_key"] == "**********"
    assert serialized["app_master_key"] == "**********"
    assert serialized["meta_app_secret"] == "**********"
    assert serialized["meta_webhook_verify_token"] == "**********"


def test_uuid_factory_produces_uuid7_compatible_ids() -> None:
    identifier = new_uuid7()

    assert identifier.version == 7
    assert identifier.variant == "specified in RFC 4122"


def test_tenant_context_is_immutable_and_transport_independent() -> None:
    context = TenantContext(
        tenant_id=new_uuid7(),
        actor_id=None,
        actor_type="system",
        correlation_id=new_uuid7(),
    )

    assert isinstance(context.tenant_id, UUID)
    with pytest.raises(FrozenInstanceError):
        context.actor_id = new_uuid7()  # type: ignore[misc]


class _TransactionContext:
    def __init__(self, session: object, events: list[str]) -> None:
        self._session = session
        self._events = events

    async def __aenter__(self) -> object:
        self._events.append("begin")
        return self._session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        self._events.append("end")


class _SessionFactory:
    def __init__(self, session: object, events: list[str]) -> None:
        self._session = session
        self._events = events

    def begin(self) -> _TransactionContext:
        return _TransactionContext(self._session, self._events)


@pytest.mark.asyncio
async def test_transaction_wraps_the_yielded_session_in_one_boundary() -> None:
    expected_session = object()
    events: list[str] = []
    factory = cast(
        async_sessionmaker[AsyncSession],
        _SessionFactory(expected_session, events),
    )

    sessions = transaction(factory)
    yielded_session = await anext(sessions)

    assert yielded_session is expected_session
    assert events == ["begin"]
    with pytest.raises(StopAsyncIteration):
        await anext(sessions)
    assert events == ["begin", "end"]
