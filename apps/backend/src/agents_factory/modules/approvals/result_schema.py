from typing import Literal, Self

from pydantic import model_validator

from agents_factory.modules.approvals.models import RequestedDecisionResult
from agents_factory.modules.integrations.google.base import InputModel


ResultStatus = Literal[
    "pending_execution", "succeeded", "rejected", "failed", "uncertain", "expired"
]
# Customer text is a reviewed template, never arbitrary reviewer/provider/model text.
RESULTS: dict[str, tuple[ResultStatus, str, tuple[str, ...]]] = {
    "approval_recorded": (
        "pending_execution",
        "La solicitud fue aprobada y está pendiente de validación y ejecución.",
        (),
    ),
    "reviewer_rejected": (
        "rejected",
        "La solicitud no fue aprobada.",
        ("contact_business",),
    ),
    "order_already_shipped": (
        "rejected",
        "El pedido ya fue despachado.",
        ("create_return_claim",),
    ),
    "appointment_already_cancelled": (
        "rejected",
        "La cita ya estaba cancelada.",
        ("contact_business",),
    ),
    "precondition_changed": (
        "rejected",
        "Las condiciones de la solicitud cambiaron y no se pudo realizar la operación.",
        ("contact_business",),
    ),
    "action_completed": ("succeeded", "La operación solicitada se completó.", ()),
    "request_recorded": (
        "succeeded",
        "La solicitud se registró para su gestión. Esto no confirma una cancelación.",
        (),
    ),
    "execution_failed": (
        "failed",
        "No se pudo completar la operación solicitada.",
        ("contact_business",),
    ),
    "connector_unavailable": (
        "failed",
        "El servicio no está disponible. No se confirmó la operación.",
        ("contact_business",),
    ),
    "outcome_unknown": (
        "uncertain",
        "No se pudo confirmar el resultado. Se requiere revisión antes de volver a intentar.",
        ("contact_business",),
    ),
    "approval_expired": (
        "expired",
        "La autorización venció y no se realizó la operación.",
        ("contact_business",),
    ),
}


class DecisionResult(InputModel):
    status: ResultStatus
    reason_code: str
    customer_safe_explanation: str
    next_actions: tuple[str, ...]

    @model_validator(mode="after")
    def safe_semantics(self) -> Self:
        expected = RESULTS.get(self.reason_code)
        if expected != (self.status, self.customer_safe_explanation, self.next_actions):
            raise ValueError(
                "decision result must use an approved, outcome-matching template"
            )
        return self

    @classmethod
    def for_reason(cls, reason_code: str) -> "DecisionResult":
        if reason_code not in RESULTS:
            raise ValueError("unknown decision result reason")
        status, explanation, actions = RESULTS[reason_code]
        return cls(
            status=status,
            reason_code=reason_code,
            customer_safe_explanation=explanation,
            next_actions=actions,
        )


def reviewer_result(
    *, decision: Literal["APPROVE", "REJECT"], proposal: RequestedDecisionResult
) -> DecisionResult:
    # The review page records authorization, not evidence of business execution.
    # Specific business reasons must be revalidated by Task 33 before telling a
    # customer they are facts; arbitrary proposal text/actions never cross here.
    return DecisionResult.for_reason(
        "approval_recorded" if decision == "APPROVE" else "reviewer_rejected"
    )


class DecisionReceipt(InputModel):
    status: Literal["CLOSED", "RECORDED", "INVALID_VERIFICATION"]
    result: DecisionResult | None = None

    @model_validator(mode="after")
    def winner_only(self) -> Self:
        if (self.status == "RECORDED") != (self.result is not None):
            raise ValueError("only the winning reviewer receives their receipt")
        return self
