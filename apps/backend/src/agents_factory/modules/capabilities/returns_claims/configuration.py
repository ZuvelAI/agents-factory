from typing import Literal
from uuid import UUID

from pydantic import Field

from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.capabilities.returns_claims.models import (
    ClaimsBinding,
    Digest,
    IssueClass,
    RequiredField,
)
from agents_factory.modules.integrations.google.base import InputModel


class ClaimsConfiguration(InputModel):
    binding: ClaimsBinding
    orders_binding_id: UUID
    policy_document_id: UUID
    policy_document_digest: Digest
    # Approved backend configuration bound to the exact policy document, not an
    # LLM interpretation of uploaded prose or customer-supplied requirements.
    policy_requirements: dict[IssueClass, tuple[RequiredField, ...]]
    environment: Literal["TEST", "PRODUCTION"] = "PRODUCTION"
    destination_digest: Digest
    enabled: bool = True
    approval_route_ref: str | None = Field(default=None, min_length=1, max_length=300)

    @property
    def digest(self) -> str:
        return NormalizedParameters.from_value(self.model_dump(mode="json")).digest
