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
from agents_factory.config import Settings, load_settings
from agents_factory.database import Database


class ReadinessProbe(Protocol):
    async def __call__(self) -> None: ...


ComponentState = Literal["up", "down"]


@dataclass(frozen=True, slots=True)
class ReadinessChecks:
    database: ReadinessProbe
    redis: ReadinessProbe

    async def evaluate(self) -> dict[str, ComponentState]:
        outcomes = await asyncio.gather(
            self.database(),
            self.redis(),
            return_exceptions=True,
        )
        return {
            "database": "down" if isinstance(outcomes[0], BaseException) else "up",
            "redis": "down" if isinstance(outcomes[1], BaseException) else "up",
        }


SettingsLoader = Callable[[], Settings]


async def _probe_redis(client: Redis) -> None:
    if not await client.ping():
        raise RuntimeError("Redis ping failed")


def create_app(
    *,
    settings_loader: SettingsLoader = load_settings,
    readiness_checks: ReadinessChecks | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = settings_loader()
        application.state.settings = settings
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
