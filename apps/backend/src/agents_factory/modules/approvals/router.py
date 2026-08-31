from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import Field
from starlette.responses import Response

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.modules.approvals.models import (
    ApprovalRequest,
    ApprovalRoute,
    ApprovalRouteDraft,
    DecideInput,
    OTPInput,
    OTPReceipt,
    PublicReceipt,
    TokenInput,
)
from agents_factory.modules.approvals.service import ApprovalService
from agents_factory.modules.integrations.google.base import InputModel


def service_for(request: Request) -> ApprovalService:
    service = getattr(request.app.state, "approval_service", None)
    if not isinstance(service, ApprovalService):
        raise HTTPException(status_code=503, detail="approval_service_unavailable")
    return service


class PrivateApprovalRoute(APIRoute):
    """Never echo token/code input through FastAPI validation errors."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                if request.url.path.startswith("/approvals/"):
                    service = service_for(request)
                    if request.headers.get("origin") != service.public_origin:
                        raise HTTPException(
                            status_code=403, detail="approval_origin_denied"
                        )
                    if request.url.query:
                        raise HTTPException(
                            status_code=400, detail="approval_body_required"
                        )
                    if (
                        request.headers.get("content-type", "").split(";", 1)[0].strip()
                        != "application/json"
                    ):
                        raise HTTPException(
                            status_code=415, detail="approval_json_required"
                        )
                    if len(await request.body()) > 16_384:
                        raise HTTPException(
                            status_code=413, detail="approval_body_too_large"
                        )
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse(
                    status_code=422, content={"detail": "invalid_approval_input"}
                )
            except DomainError as error:
                response = JSONResponse(
                    status_code=error.status, content={"detail": error.code}
                )
            except HTTPException as error:
                response = JSONResponse(
                    status_code=error.status_code, content={"detail": error.detail}
                )
            except Exception:
                # Public proofs must not enter exception telemetry or error bodies.
                response = JSONResponse(
                    status_code=500, content={"detail": "approval_unavailable"}
                )
            response.headers.update(
                {
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                }
            )
            return response

        return guarded


admin_router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/approvals",
    tags=["platform-admin-approvals"],
    route_class=PrivateApprovalRoute,
)
public_router = APIRouter(
    prefix="/approvals", tags=["approvals"], route_class=PrivateApprovalRoute
)


class ConfigureRoute(InputModel):
    configuration: ApprovalRouteDraft
    expected_revision: int = Field(default=0, ge=0)


def admin_context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id, principal.user_id, "platform_admin", request.state.correlation_id
    )


@admin_router.put("/routes")
async def configure_route(
    tenant_id: UUID, command: ConfigureRoute, request: Request, principal: PlatformAdmin
) -> ApprovalRoute:
    return await service_for(request).save_route(
        context=admin_context(request, principal, tenant_id),
        configuration=command.configuration,
        expected_revision=command.expected_revision,
    )


@admin_router.post("/actions/{action_id}")
async def request_approval(
    tenant_id: UUID, action_id: UUID, request: Request, principal: PlatformAdmin
) -> ApprovalRequest:
    return await service_for(request).request(
        context=admin_context(request, principal, tenant_id), action_id=action_id
    )


@admin_router.get("/requests/{request_id}")
async def request_status(
    tenant_id: UUID, request_id: UUID, request: Request, principal: PlatformAdmin
) -> ApprovalRequest:
    result = await service_for(request).get(
        context=admin_context(request, principal, tenant_id), request_id=request_id
    )
    if result is None:
        raise HTTPException(status_code=404, detail="approval_unavailable")
    return result


@public_router.post("/inspect")
async def inspect(command: TokenInput, request: Request) -> PublicReceipt:
    return await service_for(request).inspect(command.link_token.get_secret_value())


@public_router.post("/otp")
async def request_otp(command: OTPInput, request: Request) -> OTPReceipt:
    return await service_for(request).start_otp(command)


@public_router.post("/decide")
async def decide(command: DecideInput, request: Request) -> PublicReceipt:
    return await service_for(request).decide(
        command,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
