from __future__ import annotations

import asyncio
import time
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agents_factory.common.errors import DomainError
from agents_factory.config import (
    REQUIRED_ENVIRONMENT_VARIABLES,
    ConfigurationError,
    Settings,
    load_settings,
)
from agents_factory.main import ReadinessChecks, create_app


class _Probe:
    def __init__(
        self,
        *,
        fails: bool = False,
        hangs: bool = False,
        self_cancels: bool = False,
    ) -> None:
        self.calls = 0
        self.cancelled = False
        self.started = asyncio.Event()
        self._fails = fails
        self._hangs = hangs
        self._self_cancels = self_cancels

    async def __call__(self) -> None:
        self.calls += 1
        self.started.set()
        if self._fails:
            raise RuntimeError("dependency-secret-sentinel")
        if self._self_cancels:
            raise asyncio.CancelledError
        if self._hangs:
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True


def _settings() -> Settings:
    return Settings(
        environment="test",
        log_level="info",
        database_url=SecretStr("postgresql+asyncpg://app:secret@database/app"),
        redis_url=SecretStr("redis://:secret@redis:6379/0"),
        supabase_url="https://example.supabase.co",
        supabase_publishable_key=SecretStr("publishable-secret"),
        supabase_jwt_issuer="https://example.supabase.co/auth/v1",
        supabase_jwt_audience="authenticated",
        app_master_key=SecretStr("master-secret"),
        meta_app_secret=SecretStr("meta-app-secret"),
        meta_webhook_verify_token=SecretStr("verify-token"),
    )


def _application(
    *,
    database_fails: bool = False,
    redis_fails: bool = False,
    raise_server_exceptions: bool = True,
) -> tuple[TestClient, _Probe, _Probe]:
    database = _Probe(fails=database_fails)
    redis = _Probe(fails=redis_fails)
    application = create_app(
        settings_loader=_settings,
        readiness_checks=ReadinessChecks(database=database, redis=redis),
    )
    return (
        TestClient(
            application,
            raise_server_exceptions=raise_server_exceptions,
        ),
        database,
        redis,
    )


def test_module_app_is_import_safe_without_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in REQUIRED_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    from agents_factory.main import app

    assert app.title == "Agents Factory API"


def test_startup_reports_missing_names_without_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in REQUIRED_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    database = _Probe()
    redis = _Probe()
    application = create_app(
        settings_loader=load_settings,
        readiness_checks=ReadinessChecks(database=database, redis=redis),
    )

    with pytest.raises(ConfigurationError) as captured:
        with TestClient(application):
            pass

    assert captured.value.missing_variables == REQUIRED_ENVIRONMENT_VARIABLES
    assert "secret" not in str(captured.value).lower()
    assert database.calls == 0
    assert redis.calls == 0


def test_liveness_has_no_dependency_io() -> None:
    client, database, redis = _application()

    with client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert UUID(response.headers["x-correlation-id"]).version == 7
    assert database.calls == 0
    assert redis.calls == 0


def test_readiness_reports_each_available_dependency() -> None:
    client, database, redis = _application()

    with client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "up", "redis": "up"},
    }
    assert database.calls == 1
    assert redis.calls == 1


@pytest.mark.parametrize(
    ("database_fails", "redis_fails", "expected_checks"),
    [
        (True, False, {"database": "down", "redis": "up"}),
        (False, True, {"database": "up", "redis": "down"}),
        (True, True, {"database": "down", "redis": "down"}),
    ],
)
def test_readiness_fails_closed_after_probing_both_dependencies(
    database_fails: bool,
    redis_fails: bool,
    expected_checks: dict[str, str],
) -> None:
    client, database, redis = _application(
        database_fails=database_fails,
        redis_fails=redis_fails,
    )

    with client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": expected_checks}
    assert "dependency-secret-sentinel" not in response.text
    assert database.calls == 1
    assert redis.calls == 1


def test_readiness_times_out_one_hanging_probe_and_returns_503_quickly() -> None:
    database = _Probe(hangs=True)
    redis = _Probe()
    checks = ReadinessChecks(
        database=database,
        redis=redis,
        timeout_seconds=0.01,
    )
    application = create_app(
        settings_loader=_settings,
        readiness_checks=checks,
    )
    started_at = time.monotonic()

    with TestClient(application) as client:
        response = client.get("/health/ready")

    assert time.monotonic() - started_at < 0.5
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "down", "redis": "up"},
    }
    assert database.calls == 1
    assert redis.calls == 1
    assert database.cancelled


@pytest.mark.asyncio
async def test_external_readiness_cancellation_propagates_to_both_probes() -> None:
    database = _Probe(hangs=True)
    redis = _Probe(hangs=True)
    checks = ReadinessChecks(database=database, redis=redis)
    evaluation = asyncio.create_task(checks.evaluate())
    await asyncio.gather(database.started.wait(), redis.started.wait())

    evaluation.cancel()

    with pytest.raises(asyncio.CancelledError):
        await evaluation
    assert database.cancelled
    assert redis.cancelled


@pytest.mark.asyncio
async def test_probe_self_cancellation_is_reported_as_down() -> None:
    database = _Probe(self_cancels=True)
    redis = _Probe()
    checks = ReadinessChecks(database=database, redis=redis)

    states = await checks.evaluate()

    assert states == {"database": "down", "redis": "up"}


def test_domain_errors_are_problem_details_with_correlation_id() -> None:
    client, _, _ = _application()
    application = client.app

    @application.get("/test-domain-error")
    async def test_domain_error() -> None:
        raise DomainError(
            type="https://agents-factory.dev/problems/conflict",
            title="Conflict",
            status=409,
            detail="The requested transition is not allowed.",
            code="transition_conflict",
        )

    correlation_id = "0198f3df-cbb5-7ec9-98f8-4ca608db0f5d"
    with client:
        response = client.get(
            "/test-domain-error",
            headers={"X-Correlation-ID": correlation_id},
        )

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-correlation-id"] == correlation_id
    assert response.json() == {
        "type": "https://agents-factory.dev/problems/conflict",
        "title": "Conflict",
        "status": 409,
        "detail": "The requested transition is not allowed.",
        "code": "transition_conflict",
        "correlation_id": correlation_id,
    }


def test_unexpected_errors_are_sanitized_problem_details_with_correlation_id() -> None:
    client, _, _ = _application(raise_server_exceptions=False)
    application = client.app

    @application.get("/test-unexpected-error")
    async def test_unexpected_error() -> None:
        raise RuntimeError("unexpected-exception-secret-sentinel")

    with client:
        response = client.get("/test-unexpected-error")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    correlation_id = response.headers["x-correlation-id"]
    assert UUID(correlation_id).version == 7
    assert response.headers["x-correlation-id"] == correlation_id
    assert response.json() == {
        "type": "https://agents-factory.dev/problems/internal-server-error",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "An unexpected error occurred.",
        "code": "internal_server_error",
        "correlation_id": correlation_id,
    }
    assert "unexpected-exception-secret-sentinel" not in response.text
    assert "traceback" not in response.text.lower()


@pytest.mark.parametrize(
    "header",
    [None, "", "not-a-uuid", "\nunsafe"],
)
def test_missing_or_unsafe_correlation_headers_are_replaced(
    header: str | None,
) -> None:
    client, _, _ = _application()
    headers = {} if header is None else {"X-Correlation-ID": header}

    with client:
        response = client.get("/health/live", headers=headers)

    generated = UUID(response.headers["x-correlation-id"])
    assert generated.version == 7
