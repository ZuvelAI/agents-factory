from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.modules.actions.models import (
    ActionRecord,
    NormalizedParameters,
    PreconditionDecision,
)
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.cases.claims_contracts import (
    ClaimCase,
    ClaimCaseConflict,
    ClaimCasesPort,
    UnavailableClaimCases,
)
from agents_factory.modules.capabilities.returns_claims.completeness import merge_draft
from agents_factory.modules.capabilities.returns_claims.configuration import (
    ClaimsConfiguration,
)
from agents_factory.modules.capabilities.returns_claims.destination import (
    ClaimDestination,
)
from agents_factory.modules.capabilities.returns_claims.manifest import DEFINITIONS
from agents_factory.modules.capabilities.returns_claims.models import (
    ClaimDraft,
    ClaimStatusInput,
    ClaimSubmission,
    PreparedClaimIntake,
)
from agents_factory.modules.capabilities.returns_claims.service import (
    ClaimIntakeRejected,
    ClaimsIntakeService,
)
from agents_factory.modules.capabilities.returns_claims.sources import ClaimSources
from agents_factory.modules.identity.models import (
    AuthorizationDecision,
    IdentityAssessment,
    IdentityLevel,
)
from agents_factory.modules.integrations.contracts import (
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.integrations.google.base import InputModel
from agents_factory.modules.policies.evaluator import ActionPolicyEvaluator
from agents_factory.modules.policies.models import TenantActionPolicy


SUBMIT = "returns_claims.create_or_update_case"
STATUS = "returns_claims.get_case_status"
INPUTS: dict[str, type[InputModel]] = {
    SUBMIT: ClaimSubmission,
    STATUS: ClaimStatusInput,
}


class ClaimNeedsInformation(ValueError):
    def __init__(self, fields: tuple[str, ...]) -> None:
        self.fields = fields
        super().__init__("claim_needs_information")


class ClaimsWorkflow:
    def __init__(
        self,
        *,
        context: TenantContext,
        sessions: async_sessionmaker[AsyncSession],
        configurations: Callable[[UUID], ClaimsConfiguration | None],
        sources: ClaimSources,
        intake: ClaimsIntakeService,
        cases: ClaimCasesPort | None = None,
        destination: ClaimDestination | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.context, self.sessions, self.configurations = (
            context,
            sessions,
            configurations,
        )
        self.sources, self.intake = sources, intake
        self.cases, self.destination = cases or UnavailableClaimCases(), destination
        self.now = now or (lambda: datetime.now(UTC))

    def configuration(self, binding_id: UUID) -> ClaimsConfiguration:
        value = self.configurations(binding_id)
        if self.context.actor_id is None or self.context.actor_type not in {
            "system",
            "platform_admin",
        }:
            raise ClaimIntakeRejected("backend_actor_required")
        if (
            value is None
            or not value.enabled
            or value.binding.tenant_id != self.context.tenant_id
            or value.binding.binding_id != binding_id
        ):
            raise ClaimIntakeRejected("claim_binding_unavailable")
        return value

    def supports(self, configuration: ClaimsConfiguration, operation: str) -> bool:
        return (
            operation in DEFINITIONS
            and self.cases.available
            and (
                operation == STATUS
                or (
                    self.destination is not None
                    and self.destination.available
                    and self.destination.digest == configuration.destination_digest
                )
            )
        )

    async def identity(
        self,
        configuration: ClaimsConfiguration,
        customer_ref: str,
        action_id: UUID,
        level: int,
    ) -> IdentityAssessment:
        identity = await self.sources.identity(
            configuration, customer_ref, action_id, level
        )
        if (
            identity.tenant_id != self.context.tenant_id
            or identity.customer_ref != customer_ref
            or identity.achieved_level < level
            or identity.assessed_at.tzinfo is None
            or not timedelta(seconds=-30)
            <= self.now() - identity.assessed_at
            <= timedelta(minutes=5)
        ):
            raise ClaimIntakeRejected("claim_identity_required")
        return identity

    def scoped_case(
        self,
        case: ClaimCase | None,
        configuration: ClaimsConfiguration,
        customer_ref: str,
        *,
        case_id: UUID | None = None,
        key: str | None = None,
    ) -> ClaimCase:
        if (
            case is None
            or (case.intake.tenant_id, case.intake.customer_ref, case.intake.binding_id)
            != (self.context.tenant_id, customer_ref, configuration.binding.binding_id)
            or (case_id is not None and case.case_id != case_id)
            or (key is not None and case.intake.deduplication_key != key)
        ):
            raise ClaimIntakeRejected("claim_case_unavailable")
        return case

    async def prepare(
        self,
        configuration: ClaimsConfiguration,
        customer_ref: str,
        action_id: UUID,
        message_id: UUID,
        identity: IdentityAssessment,
        submission: ClaimSubmission,
    ) -> tuple[PreparedClaimIntake, ClaimCase | None]:
        draft = ClaimDraft.model_validate(submission.model_dump(exclude={"case_id"}))
        previous = None
        if submission.case_id is not None:
            previous = self.scoped_case(
                await self.cases.get(
                    context=self.context,
                    customer_ref=customer_ref,
                    case_id=submission.case_id,
                ),
                configuration,
                customer_ref,
                case_id=submission.case_id,
            )
        combined = merge_draft(previous.intake.draft, draft) if previous else draft
        policy = await self.sources.policy(configuration)
        reference = await self.sources.reference(
            configuration, customer_ref, action_id, combined
        )
        prepared = await self.intake.prepare(
            context=self.context,
            binding=configuration.binding,
            customer_ref=customer_ref,
            assessment=identity,
            message_id=message_id,
            draft=draft,
            policy=policy,
            order_reference=reference,
            previous=previous.intake if previous else None,
        )
        if prepared.deduplication_key is None:
            if prepared.completeness.missing_fields:
                raise ClaimNeedsInformation(prepared.completeness.missing_fields)
            raise ClaimIntakeRejected("claim_order_reference_unavailable")
        if previous is None:
            found = await self.cases.find_open(
                context=self.context,
                customer_ref=customer_ref,
                deduplication_key=prepared.deduplication_key,
            )
            if found is not None:
                previous = self.scoped_case(
                    found, configuration, customer_ref, key=prepared.deduplication_key
                )
                combined = merge_draft(previous.intake.draft, draft)
                reference = await self.sources.reference(
                    configuration, customer_ref, action_id, combined
                )
                prepared = await self.intake.prepare(
                    context=self.context,
                    binding=configuration.binding,
                    customer_ref=customer_ref,
                    assessment=identity,
                    message_id=message_id,
                    draft=draft,
                    policy=policy,
                    order_reference=reference,
                    previous=previous.intake,
                )
        if previous is not None and previous.status not in {
            "OPEN",
            "AWAITING_INFORMATION",
            "READY_FOR_REVIEW",
        }:
            raise ClaimIntakeRejected("claim_backoffice_review_in_progress")
        return prepared, previous

    async def request_action(
        self,
        *,
        actions: ActionService,
        action_id: UUID,
        message_id: UUID,
        conversation_id: UUID,
        customer_ref: str,
        binding_id: UUID,
        operation: str,
        arguments: dict[str, object],
        tenant_policy: TenantActionPolicy | None = None,
    ) -> ActionRecord:
        configuration = self.configuration(binding_id)
        if not self.supports(configuration, operation):
            raise ClaimIntakeRejected("claim_operation_unavailable")
        args = INPUTS[operation].model_validate(arguments).model_dump(mode="json")
        definition = DEFINITIONS[operation]
        requirement = ActionPolicyEvaluator().evaluate(
            risk=definition.risk,
            minimum_identity_level=IdentityLevel(definition.required_identity_level),
            tenant_policy=tenant_policy,
        )
        identity = await self.identity(
            configuration, customer_ref, action_id, int(requirement.identity_level)
        )
        request_digest = NormalizedParameters.from_value(args).digest
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            existing = await ActionRepository(session, self.context).get(action_id)
        if existing is not None:
            if (
                existing.customer_ref,
                existing.conversation_id,
                existing.connector_binding_id,
                existing.action_type,
                existing.parameters.get("_request_digest"),
                existing.parameters.get("_message_id"),
            ) != (
                customer_ref,
                conversation_id,
                binding_id,
                operation,
                request_digest,
                str(message_id),
            ):
                raise ClaimIntakeRejected("claim_action_replay_conflict")
            return existing
        params: dict[str, object] = {
            "_configuration_digest": configuration.digest,
            "_request_digest": request_digest,
            "_message_id": str(message_id),
        }
        if operation == SUBMIT:
            prepared, previous = await self.prepare(
                configuration,
                customer_ref,
                action_id,
                message_id,
                identity,
                ClaimSubmission.model_validate(args),
            )
            params.update(
                {
                    "draft": prepared.draft.model_dump(mode="json"),
                    "_intake": prepared.model_dump(mode="json"),
                    "_expected_revision": previous.revision if previous else 0,
                    "_case_id": str(previous.case_id) if previous else None,
                }
            )
            resource = str(prepared.deduplication_key)
        else:
            payload = ClaimStatusInput.model_validate(args)
            self.scoped_case(
                await self.cases.get(
                    context=self.context,
                    customer_ref=customer_ref,
                    case_id=payload.case_id,
                ),
                configuration,
                customer_ref,
                case_id=payload.case_id,
            )
            params["case_id"] = str(payload.case_id)
            resource = str(payload.case_id)
        return await actions.request(
            action_id=action_id,
            conversation_id=conversation_id,
            customer_ref=customer_ref,
            capability="returns_claims",
            action_type=operation,
            risk=definition.risk,
            minimum_identity_level=IdentityLevel(definition.required_identity_level),
            tenant_policy=tenant_policy,
            assessment=identity,
            authorization=AuthorizationDecision(
                tenant_id=self.context.tenant_id,
                customer_ref=customer_ref,
                resource_type="claim",
                resource_id=resource,
                action=operation,
                allowed=True,
                reason_code="scoped_claim_intake",
            ),
            resource_type="claim",
            resource_id=resource,
            parameters=params,
            approval_route_ref=configuration.approval_route_ref
            if requirement.approval_required
            else None,
            connector_binding_id=binding_id,
            connector_name="returns_claims",
            requested_at=self.now(),
        )

    async def revalidate_intake(
        self,
        action: ActionRecord,
        configuration: ClaimsConfiguration,
        identity: IdentityAssessment,
    ) -> PreparedClaimIntake:
        prepared = PreparedClaimIntake.model_validate(action.parameters.get("_intake"))
        reference = await self.sources.reference(
            configuration, action.customer_ref, action.id, prepared.draft
        )
        current = await self.intake.prepare(
            context=self.context,
            binding=configuration.binding,
            customer_ref=action.customer_ref,
            assessment=identity,
            message_id=UUID(str(action.parameters["_message_id"])),
            draft=prepared.draft,
            policy=await self.sources.policy(configuration),
            order_reference=reference,
        )
        if (
            prepared.content_digest != current.content_digest
            or prepared.deduplication_key != current.deduplication_key
            or prepared.tenant_id != self.context.tenant_id
            or prepared.customer_ref != action.customer_ref
            or prepared.binding_id != configuration.binding.binding_id
            or action.parameters.get("draft") != prepared.draft.model_dump(mode="json")
        ):
            raise ClaimIntakeRejected("claim_intake_changed")
        return prepared

    async def perform(
        self, action: ActionRecord, prepared: PreparedClaimIntake | None
    ) -> ConnectorResult:
        configuration = self.configuration(action.connector_binding_id)
        if configuration.digest != action.parameters.get(
            "_configuration_digest"
        ) or not self.supports(configuration, action.action_type):
            return ConnectorResult(
                operation=action.action_type,
                status="REJECTED",
                error_code="claim_configuration_changed",
            )
        if action.action_type == STATUS:
            case_id = UUID(str(action.parameters["case_id"]))
            case = self.scoped_case(
                await self.cases.get(
                    context=self.context,
                    customer_ref=action.customer_ref,
                    case_id=case_id,
                ),
                configuration,
                action.customer_ref,
                case_id=case_id,
            )
            return ConnectorResult(
                operation=STATUS,
                status="SUCCEEDED",
                data={
                    "case_id": str(case.case_id),
                    "case_status": case.status,
                    "customer_result": case.customer_result,
                    "result_source": "backoffice"
                    if case.customer_result is not None
                    else None,
                },
            )
        assert prepared is not None
        try:
            raw_id = action.parameters.get("_case_id")
            existing_case_id = UUID(str(raw_id)) if raw_id is not None else None
            case = self.scoped_case(
                await self.cases.upsert(
                    context=self.context,
                    action_id=action.id,
                    parameter_digest=action.parameter_digest,
                    intake=prepared,
                    expected_revision=int(str(action.parameters["_expected_revision"])),
                    case_id=existing_case_id,
                ),
                configuration,
                action.customer_ref,
                case_id=existing_case_id,
                key=prepared.deduplication_key,
            )
            if (
                case.intake.content_digest != prepared.content_digest
                or case.status != prepared.completeness.state
            ):
                raise ValueError("claim_receipt_mismatch")
        except ClaimCaseConflict:
            return ConnectorResult(
                operation=SUBMIT,
                status="REJECTED",
                error_code="claim_changed_requires_confirmation",
            )
        # A saved case is still saved if an external destination is down. Report
        # delivery separately; never invite a blind repeat of case creation.
        try:
            assert self.destination is not None
            delivery = await self.destination.deliver(context=self.context, case=case)
        except Exception:
            delivery = {"state": "UNCONFIRMED_REQUIRES_REVIEW"}
        return ConnectorResult(
            operation=SUBMIT,
            status="SUCCEEDED",
            data={
                "case_id": str(case.case_id),
                "case_status": case.status,
                "case_created": True,
                "revision": case.revision,
                "missing_fields": case.intake.completeness.missing_fields,
                "review_flags": case.intake.completeness.review_flags,
                "delivery": delivery,
                "resolution_promised": False,
                "business_decision": "NOT_MADE",
            },
        )


class ClaimsActionConnector:
    def __init__(self, workflow: ClaimsWorkflow) -> None:
        self.workflow = workflow
        self._permits: dict[str, tuple[ActionRecord, PreparedClaimIntake | None]] = {}

    def is_safe_read(self, operation: str) -> bool:
        return operation == STATUS

    async def revalidate(self, action: ActionRecord) -> PreconditionDecision:
        self._permits.pop(str(action.id), None)
        try:
            configuration = self.workflow.configuration(action.connector_binding_id)
            definition = DEFINITIONS[action.action_type]
            identity = await self.workflow.identity(
                configuration,
                action.customer_ref,
                action.id,
                max(
                    int(action.required_identity_level),
                    definition.required_identity_level,
                ),
            )
            confirmed = (
                action.confirmed_at is not None
                and action.confirmation_expires_at is not None
                and self.workflow.now() < action.confirmation_expires_at
                and action.confirmation_digest
                == hashlib.sha256(
                    f"{action.id}:{action.customer_ref}:{action.parameter_digest}:confirmed".encode()
                ).hexdigest()
            )
            ready = action.state == "CONFIRMED" and not action.approval_required
            approved = (
                action.state == "AWAITING_APPROVAL"
                and action.approval_required
                and action.approved_at is not None
                and bool(action.approval_reference)
                and action.approval_route_ref == configuration.approval_route_ref
                and bool(configuration.approval_route_ref)
            )
            if not (
                action.tenant_id == self.workflow.context.tenant_id
                and action.capability == "returns_claims"
                and action.connector_name == "returns_claims"
                and action.risk == definition.risk
                and action.required_identity_level >= definition.required_identity_level
                and action.parameter_digest
                == NormalizedParameters.from_value(action.parameters).digest
                and configuration.digest
                == action.parameters.get("_configuration_digest")
                and self.workflow.supports(configuration, action.action_type)
                and (ready or approved)
                and (
                    not definition.requires_confirmation or action.confirmation_required
                )
                and (not action.confirmation_required or confirmed)
            ):
                raise ClaimIntakeRejected("claim_action_not_authorized")
            prepared = (
                await self.workflow.revalidate_intake(action, configuration, identity)
                if action.action_type == SUBMIT
                else None
            )
        except Exception:
            return PreconditionDecision(
                valid=False, reason_code="claim_precondition_failed"
            )
        self._permits[str(action.id)] = (action, prepared)
        return PreconditionDecision(valid=True, reason_code="ready")

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        permit = self._permits.get(request.idempotency_key or "")
        if permit is None:
            return ConnectorResult(
                operation=request.operation,
                status="REJECTED",
                error_code="claim_action_not_authorized",
            )
        action, prepared = permit
        if (
            request.tenant_id,
            request.binding_id,
            request.operation,
            NormalizedParameters.from_value(request.arguments).digest,
        ) != (
            action.tenant_id,
            action.connector_binding_id,
            action.action_type,
            action.parameter_digest,
        ):
            return ConnectorResult(
                operation=request.operation,
                status="REJECTED",
                error_code="claim_action_not_authorized",
            )
        if request.operation == SUBMIT:
            self._permits.pop(str(action.id), None)
        return await self.workflow.perform(action, prepared)
