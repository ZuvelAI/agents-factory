from __future__ import annotations

from fastapi import APIRouter

from agents_factory.common.security import PlatformAdmin
from agents_factory.modules.capabilities.contracts import CapabilityManifest
from agents_factory.modules.capabilities.registry import V1_CAPABILITY_REGISTRY


router = APIRouter(prefix="/admin/capabilities", tags=["platform-admin-capabilities"])


@router.get("", response_model=tuple[CapabilityManifest, ...])
async def list_capabilities(principal: PlatformAdmin) -> tuple[CapabilityManifest, ...]:
    _ = principal
    return V1_CAPABILITY_REGISTRY.list()
