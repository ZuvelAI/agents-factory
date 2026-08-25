from dataclasses import dataclass
from typing import Literal
from uuid import UUID


ActorType = Literal["platform_admin", "customer", "system", "approver"]


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Transport-independent identity and tenant boundary for one operation."""

    tenant_id: UUID
    actor_id: UUID | None
    actor_type: ActorType
    correlation_id: UUID
