import asyncio
from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from agents_factory.modules.handoffs.models import (
    HandoffError,
    HumanResponseSurface,
    HumanSurfaceOption,
    SurfaceBinding,
    VerifiedHumanEvent,
)


class HumanSurfaceAdapter(Protocol):
    """Deployment-owned adapter: verify routing AND authenticated control events.

    No generic REST URLs or client-supplied 'verified' flag. Verification must prove
    the binding belongs to this tenant/account and can route to its human surface.
    load_event must authenticate and durably deduplicate provider evidence before
    returning its monotonic per-handoff sequence. Adapters must not perform AI sends.
    """

    surface: HumanResponseSurface

    async def verify(
        self, *, tenant_id: UUID, account_id: UUID, binding: SurfaceBinding
    ) -> bool: ...

    async def load_event(self, event_ref: str) -> VerifiedHumanEvent: ...


class HumanSurfaceRegistry:
    def __init__(
        self, adapters: Mapping[str, HumanSurfaceAdapter] | None = None
    ) -> None:
        self._adapters = dict(adapters or {})

    def adapter(self, binding: SurfaceBinding) -> HumanSurfaceAdapter:
        adapter = self._adapters.get(binding.adapter)
        if adapter is None or adapter.surface != binding.surface:
            raise HandoffError("human_surface_not_supported")
        return adapter

    def options(self) -> tuple[HumanSurfaceOption, ...]:
        return tuple(
            HumanSurfaceOption(surface=adapter.surface, adapter=name)
            for name, adapter in sorted(self._adapters.items())
        )

    async def verify(
        self, *, tenant_id: UUID, account: Mapping[str, object], binding: SurfaceBinding
    ) -> None:
        validate_account(account, binding)
        adapter = self.adapter(binding)
        try:
            verified = await asyncio.wait_for(
                adapter.verify(
                    tenant_id=tenant_id,
                    account_id=UUID(str(account["id"])),
                    binding=binding,
                ),
                timeout=5,
            )
        except Exception:
            raise HandoffError("human_surface_verification_failed") from None
        if verified is not True:
            raise HandoffError("human_surface_not_verified")

    async def event(
        self, binding: SurfaceBinding, event_ref: str
    ) -> VerifiedHumanEvent:
        if not event_ref or len(event_ref) > 200:
            raise HandoffError("human_event_unavailable")
        try:
            event = await asyncio.wait_for(
                self.adapter(binding).load_event(event_ref), 5
            )
        except Exception:
            raise HandoffError("human_event_unavailable") from None
        if not isinstance(event, VerifiedHumanEvent) or event.binding != binding:
            raise HandoffError("human_event_unavailable")
        return event


def validate_account(account: Mapping[str, object], binding: SurfaceBinding) -> None:
    if account["status"] != "active":
        raise HandoffError("human_surface_account_inactive")
    if binding.surface == HumanResponseSurface.WHATSAPP_COEXISTENCE and (
        account["mode"] != "COEXISTENCE"
        or account["coexistence_eligibility"] != "ELIGIBLE"
        or account["health_status"] != "HEALTHY"
        or account["verified_at"] is None
    ):
        raise HandoffError("coexistence_not_verified")
