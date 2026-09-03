from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, SecretStr, field_validator, model_validator

from agents_factory.common.errors import DomainError
from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.integrations.google.base import InputModel
from agents_factory.modules.integrations.google.gmail import Mailbox


ApprovalState = Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED", "INVALIDATED"]
MailState = Literal["PENDING", "CLAIMED", "SENT", "FAILED", "UNCERTAIN"]


class ApprovalError(DomainError):
    def __init__(
        self, code: str = "approval_unavailable", *, status: int = 409
    ) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/approval-unavailable",
            title="Approval Unavailable",
            status=status,
            detail=code,
            code=code,
        )


class ApprovalRouteDraft(InputModel):
    ref: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$")
    capability: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    action: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    authorized_emails: tuple[Mailbox, ...] = Field(min_length=1, max_length=50)
    strategy: Literal["first_response"] = "first_response"
    enabled: bool = True
    expires_minutes: int = Field(default=1440, ge=1, le=10080)
    otp_seconds: int = Field(default=600, ge=30, le=600)
    otp_max_attempts: int = Field(default=5, ge=1, le=5)
    otp_max_sends: int = Field(default=3, ge=1, le=5)
    otp_cooldown_seconds: int = Field(default=60, ge=30, le=600)

    @field_validator("authorized_emails", mode="before")
    @classmethod
    def normalized_addresses(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(
                item.strip().lower() if isinstance(item, str) else item
                for item in value
            )
        return value

    @model_validator(mode="after")
    def valid_route(self) -> Self:
        if not self.action.startswith(self.capability + ".") or len(
            set(self.authorized_emails)
        ) != len(self.authorized_emails):
            raise ValueError("approval route scope/recipients mismatch")
        return self

    @property
    def digest(self) -> str:
        return NormalizedParameters.from_value(self.model_dump(mode="json")).digest


class ApprovalRoute(InputModel):
    id: UUID
    tenant_id: UUID
    revision: int = Field(ge=1)
    configuration: ApprovalRouteDraft
    digest: str


class ApprovalRequest(InputModel):
    id: UUID
    tenant_id: UUID
    action_id: UUID
    parameter_digest: str
    route_id: UUID
    route_digest: str
    state: ApprovalState
    expires_at: AwareDatetime
    created_at: AwareDatetime
    closed_at: AwareDatetime | None = None


class ApprovalLink(InputModel):
    id: UUID
    tenant_id: UUID
    request_id: UUID
    email: Mailbox
    token_digest: str
    notice_state: MailState = "PENDING"
    invalidated_at: AwareDatetime | None = None
    challenge_id: UUID | None = None
    otp_digest: str | None = Field(default=None, repr=False)
    otp_expires_at: AwareDatetime | None = None
    otp_attempts: int = 0
    otp_sends: int = 0
    last_sent_at: AwareDatetime | None = None
    otp_delivery: MailState = "PENDING"


class RequestedDecisionResult(InputModel):
    """Reviewer proposal, NOT an execution result or an automatic customer reply."""

    reason_code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    explanation: str = Field(min_length=1, max_length=2000)
    requested_next_actions: tuple[str, ...] = Field(default=(), max_length=10)

    @field_validator("explanation")
    @classmethod
    def nonempty_explanation(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an explanation is required")
        return value.strip()

    @field_validator("requested_next_actions")
    @classmethod
    def codes_only(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        import re

        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", item) for item in values):
            raise ValueError("next actions must be structured codes")
        return values


class ApprovalDecision(InputModel):
    id: UUID
    tenant_id: UUID
    request_id: UUID
    action_id: UUID
    parameter_digest: str
    approver_email: Mailbox
    decision: Literal["APPROVE", "REJECT"]
    requested_result: RequestedDecisionResult
    decided_at: AwareDatetime
    verification: Literal["LINK_AND_EMAIL_OTP"] = "LINK_AND_EMAIL_OTP"
    metadata: dict[str, str] = Field(default_factory=dict)


class TokenInput(InputModel):
    link_token: SecretStr = Field(min_length=1, max_length=300, repr=False)


class OTPInput(TokenInput):
    email: Mailbox

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class VerifyInput(OTPInput):
    challenge_id: UUID
    code: SecretStr = Field(min_length=1, max_length=64, repr=False)


class DecideInput(VerifyInput):
    decision: Literal["APPROVE", "REJECT"]
    requested_result: RequestedDecisionResult


class OTPReceipt(InputModel):
    status: Literal["IF_AUTHORIZED_SENT"] = "IF_AUTHORIZED_SENT"
    challenge_id: UUID


class PublicReceipt(InputModel):
    status: Literal["OPEN", "CLOSED", "RECORDED", "INVALID_VERIFICATION"]


class ReviewDetails(InputModel):
    request_id: UUID
    action: str
    resource_reference: str | None = None
    expires_at: AwareDatetime


class ReviewReceipt(InputModel):
    status: Literal["OPEN", "CLOSED", "INVALID_VERIFICATION"]
    details: ReviewDetails | None = None
