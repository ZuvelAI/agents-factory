from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class AgentOperationState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    agent_instance_id: UUID
    enabled: bool
    revision: int
    resumed_at: datetime | None
    updated_at: datetime


class OperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    expected_revision: int = Field(strict=True, ge=1)


class AgentOperationView(AgentOperationState):
    controls_available: bool = False
