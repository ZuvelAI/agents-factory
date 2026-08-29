import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from agents_factory.common.errors import DomainError
from agents_factory.common.ids import correlation_id_from_header
from agents_factory.common.security import (
    JwksTokenVerifier,
    PlatformAdminAuthorizer,
    TokenVerifier,
)
from agents_factory.config import Settings, load_settings
from agents_factory.database import Database
from agents_factory.modules.agent_factory.router import router as admin_agent_spec_router
from agents_factory.modules.tenants.admin_router import router as admin_tenant_router
from agents_factory.modules.whatsapp.webhook import router as meta_whatsapp_router
from agents_factory.modules.whatsapp.router import router as admin_whatsapp_router


class ReadinessProbe(Protocol):
    async def __call__(self) -> None: ...


ComponentState = Literal["up", "down"]
COMPOSE_HEALTHCHECK_CLIENT_TIMEOUT_SECONDS = 2.0
DEFAULT_READINESS_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class ReadinessChecks:
    database: ReadinessProbe
    redis: ReadinessProbe
    timeout_seconds: float = DEFAULT_READINESS_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds < COMPOSE_HEALTHCHECK_CLIENT_TIMEOUT_SECONDS:
            raise ValueError(
                "readiness timeout must be positive and shorter than the "
                "Compose healthcheck client timeout"
            )

    async def evaluate(self) -> dict[str, ComponentState]:
        tasks = (
            asyncio.create_task(self._evaluate_probe(self.database)),
            asyncio.create_task(self._evaluate_probe(self.redis)),
        )
        try:
            outcomes = await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return {
            "database": outcomes[0],
            "redis": outcomes[1],
        }

    async def _evaluate_probe(self, probe: ReadinessProbe) -> ComponentState:
        probe_task = asyncio.create_task(probe())
        try:
            await asyncio.wait_for(
                asyncio.shield(probe_task),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            await _cancel_probe(probe_task)
            return "down"
        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                await _cancel_probe(probe_task)
                raise
            return "down"
        except Exception:
            return "down"
        return "up"


SettingsLoader = Callable[[], Settings]


async def _cancel_probe(probe_task: asyncio.Task[None]) -> None:
    if not probe_task.done():
        probe_task.cancel()
    await asyncio.gather(probe_task, return_exceptions=True)


async def _probe_redis(client: Redis) -> None:
    if not await client.ping():
        raise RuntimeError("Redis ping failed")


def create_app(
    *,
    settings_loader: SettingsLoader = load_settings,
    readiness_checks: ReadinessChecks | None = None,
    token_verifier: TokenVerifier | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = settings_loader()
        application.state.settings = settings
        verifier = token_verifier or JwksTokenVerifier(
            issuer=settings.supabase_jwt_issuer,
            audience=settings.supabase_jwt_audience,
        )
        application.state.platform_admin_authorizer = PlatformAdminAuthorizer(verifier)
        database: Database | None = None
        redis_client: Redis | None = None

        if readiness_checks is None:
            database = Database(settings.database_url)
            redis_client = Redis.from_url(
                settings.redis_url.get_secret_value(),
                decode_responses=True,
            )
            application.state.database = database
            application.state.redis = redis_client
            application.state.readiness_checks = ReadinessChecks(
                database=database.ping,
                redis=lambda: _probe_redis(redis_client),
            )
        else:
            application.state.readiness_checks = readiness_checks

        try:
            yield
        finally:
            if redis_client is not None:
                await redis_client.aclose()
            if database is not None:
                await database.dispose()

    application = FastAPI(title="Agents Factory API", lifespan=lifespan)
    application.include_router(admin_tenant_router)
    application.include_router(admin_agent_spec_router)
    application.include_router(admin_whatsapp_router)
    application.include_router(meta_whatsapp_router)

    @application.middleware("http")
    async def correlate_request(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        correlation_id = correlation_id_from_header(
            request.headers.get("X-Correlation-ID")
        )
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = str(correlation_id)
        return response

    @application.exception_handler(DomainError)
    async def handle_domain_error(
        request: Request,
        error: DomainError,
    ) -> JSONResponse:
        correlation_id = str(request.state.correlation_id)
        return JSONResponse(
            status_code=error.status,
            content=error.to_problem_details(correlation_id=correlation_id),
            media_type="application/problem+json",
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        _error: Exception,
    ) -> JSONResponse:
        correlation_id = str(request.state.correlation_id)
        error = DomainError(
            type="https://agents-factory.dev/problems/internal-server-error",
            title="Internal Server Error",
            status=500,
            detail="An unexpected error occurred.",
            code="internal_server_error",
        )
        return JSONResponse(
            status_code=error.status,
            content=error.to_problem_details(correlation_id=correlation_id),
            media_type="application/problem+json",
            headers={"X-Correlation-ID": correlation_id},
        )

    @application.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @application.get("/health/ready")
    async def ready(request: Request) -> JSONResponse:
        checks: ReadinessChecks = request.app.state.readiness_checks
        states = await checks.evaluate()
        is_ready = all(state == "up" for state in states.values())
        return JSONResponse(
            status_code=200 if is_ready else 503,
            content={
                "status": "ready" if is_ready else "not_ready",
                "checks": states,
            },
        )

    return application


app = create_app()
