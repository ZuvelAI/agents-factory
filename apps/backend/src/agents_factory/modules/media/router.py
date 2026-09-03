from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response

from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.modules.media.contracts import MediaError
from agents_factory.modules.media.service import MediaService


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/media", tags=["platform-admin-media"]
)


def _context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id,
        principal.user_id,
        "platform_admin",
        UUID(str(getattr(request.state, "correlation_id", uuid4()))),
    )


def _service(request: Request) -> MediaService:
    service = getattr(request.app.state, "media_service", None)
    if not isinstance(service, MediaService):
        raise HTTPException(status_code=503, detail="media_service_unavailable")
    return service


@router.post("/{media_id}/access")
async def access(
    tenant_id: UUID, media_id: UUID, request: Request, principal: PlatformAdmin
) -> dict[str, str]:
    service, context = _service(request), _context(request, principal, tenant_id)
    record = await service._get(context, media_id)
    if record is None:
        raise HTTPException(status_code=404, detail="media_unavailable")
    try:
        url = await service.signed_access(
            context=context, customer_ref=record.customer_ref, evidence_id=media_id
        )
    except MediaError:
        raise HTTPException(status_code=404, detail="media_unavailable") from None
    return {"url": url}


@router.get("/{media_id}/download")
async def download(
    tenant_id: UUID,
    media_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    expires: int,
    signature: str = Query(min_length=64, max_length=64, pattern="^[a-f0-9]{64}$"),
) -> Response:
    service, context = _service(request), _context(request, principal, tenant_id)
    record = await service._get(context, media_id)
    if record is None:
        raise HTTPException(status_code=404, detail="media_unavailable")
    try:
        content = await service.read_signed(
            context=context,
            customer_ref=record.customer_ref,
            evidence_id=media_id,
            expires=expires,
            signature=signature,
        )
    except MediaError:
        raise HTTPException(status_code=404, detail="media_unavailable") from None
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{media_id}"',
        },
    )


@router.delete("/{media_id}", status_code=204)
async def delete(
    tenant_id: UUID, media_id: UUID, request: Request, principal: PlatformAdmin
) -> Response:
    try:
        await _service(request).delete(
            context=_context(request, principal, tenant_id), evidence_id=media_id
        )
    except MediaError:
        raise HTTPException(status_code=404, detail="media_unavailable") from None
    return Response(status_code=204)
