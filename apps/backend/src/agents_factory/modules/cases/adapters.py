from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.capabilities.returns_claims.models import (
    PreparedClaimIntake,
)
from agents_factory.modules.cases.claims_contracts import ClaimCase, ClaimCaseConflict
from agents_factory.modules.cases.contracts import CaseIntake, CaseReceipt
from agents_factory.modules.cases.models import CaseRecord, CaseSubmission
from agents_factory.modules.cases.service import CaseService


def claim_receipt(case: CaseRecord) -> ClaimCase:
    if case.capability != "returns_claims":
        raise ClaimCaseConflict("case_capability_mismatch")
    return ClaimCase(
        case_id=case.id,
        intake=PreparedClaimIntake.model_validate(case.intake),
        revision=case.revision,
        status=case.status,
        customer_result=case.customer_result,
        result_recorded_by=case.result_recorded_by,
    )


class PersistentClaimCases:
    available = True

    def __init__(self, service: CaseService) -> None:
        self.service = service

    async def find_open(
        self, *, context: TenantContext, customer_ref: str, deduplication_key: str
    ) -> ClaimCase | None:
        case = await self.service.find_open(
            context=context,
            customer_ref=customer_ref,
            deduplication_key=deduplication_key,
        )
        return claim_receipt(case) if case else None

    async def get(
        self, *, context: TenantContext, customer_ref: str, case_id: UUID
    ) -> ClaimCase | None:
        case = await self.service.get(
            context=context, customer_ref=customer_ref, case_id=case_id
        )
        return claim_receipt(case) if case else None

    async def upsert(
        self,
        *,
        context: TenantContext,
        action_id: UUID,
        parameter_digest: str,
        intake: PreparedClaimIntake,
        expected_revision: int,
        case_id: UUID | None,
    ) -> ClaimCase:
        if (
            intake.order_reference is None
            or intake.draft.issue_type is None
            or intake.deduplication_key is None
        ):
            raise ClaimCaseConflict("case_scoped_resource_required")
        content = NormalizedParameters.from_value(
            {
                "draft": intake.draft.model_dump(mode="json"),
                "deduplication_key": intake.deduplication_key,
                "policy": intake.policy.model_dump(mode="json")
                if intake.policy
                else None,
                "order_reference": intake.order_reference.model_dump(mode="json"),
                "completeness": intake.completeness.model_dump(mode="json"),
            }
        ).digest
        if content != intake.content_digest:
            raise ClaimCaseConflict("case_content_digest_mismatch")
        return claim_receipt(
            await self.service.find_or_create(
                context=context,
                operation_id=action_id,
                parameter_digest=parameter_digest,
                expected_revision=expected_revision,
                case_id=case_id,
                submission=CaseSubmission(
                    tenant_id=intake.tenant_id,
                    customer_ref=intake.customer_ref,
                    capability="returns_claims",
                    issue_type=intake.draft.issue_type,
                    binding_id=intake.binding_id,
                    resource_id=intake.order_reference.resource_id,
                    deduplication_key=intake.deduplication_key,
                    content_digest=intake.content_digest,
                    intake=intake.model_dump(mode="json"),
                    initial_status=intake.completeness.state,
                    evidence_ids=intake.draft.evidence_ids,
                ),
            )
        )


class PersistentOrderCases:
    available = True

    def __init__(self, service: CaseService) -> None:
        self.service = service

    async def create_or_update(
        self, *, context: TenantContext, intake: CaseIntake
    ) -> CaseReceipt:
        content = intake.model_dump(
            mode="json", exclude={"idempotency_key", "conversation_id"}
        )
        digest = NormalizedParameters.from_value(content).digest
        record = await self.service.find_or_create(
            context=context,
            operation_id=intake.idempotency_key,
            parameter_digest=NormalizedParameters.from_value(
                intake.model_dump(mode="json")
            ).digest,
            submission=CaseSubmission(
                tenant_id=intake.tenant_id,
                customer_ref=intake.customer_ref,
                capability="orders",
                issue_type=intake.issue_type,
                binding_id=intake.binding_id,
                resource_id=intake.resource_id,
                deduplication_key=intake.deduplication_key,
                content_digest=digest,
                intake=intake.model_dump(mode="json"),
                initial_status="READY_FOR_REVIEW",
                evidence_ids=intake.evidence_ids,
            ),
        )
        # Creation is represented by the first action link, not guessed from time.
        events = await self.service.history(
            context=context, customer_ref=intake.customer_ref, case_id=record.id
        )
        reused = not any(
            event.event_type == "CREATED"
            and event.action_reference == intake.idempotency_key
            for event in events
        )
        return CaseReceipt(
            case_id=record.id,
            tenant_id=record.tenant_id,
            customer_ref=record.customer_ref,
            deduplication_key=record.deduplication_key,
            status=record.status,
            reused=reused,
        )
