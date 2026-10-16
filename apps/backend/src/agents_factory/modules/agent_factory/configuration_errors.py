"""Safe request-validation boundary: rejected values never leave the API."""

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import uuid4

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse


class SafeConfigurationRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as error:
                fields = []
                for issue in error.errors():
                    location = issue.get("loc", ())
                    # Unknown extra keys are user-controlled too: omit their name.
                    if issue["type"] == "extra_forbidden":
                        location = location[:-1]
                    fields.append(
                        {"field": ".".join(map(str, location)), "code": issue["type"]}
                    )
                return JSONResponse(
                    status_code=422,
                    media_type="application/problem+json",
                    content={
                        "type": "https://agents-factory.dev/problems/configuration-validation",
                        "title": "Configuration validation failed",
                        "status": 422,
                        "detail": "Revisa los campos indicados; no se guardaron cambios.",
                        "code": "configuration_validation_failed",
                        "correlation_id": str(uuid4()),
                        "errors": fields,
                    },
                )

        return safe_handler
