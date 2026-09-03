from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context
from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.capabilities.returns_claims.models import (
    PreparedClaimIntake,
)
from agents_factory.modules.cases.claims_contracts import ClaimCaseConflict
from agents_factory.modules.cases.contracts import CaseStatus
from agents_factory.modules.cases.deduplication import case_key
from agents_factory.modules.cases.models import (
    CaseEvent,
    CasePolicy,
    CaseRecord,
    CaseSubmission,
    CaseTransition,
    CustomerCaseStatus,
)
from agents_factory.modules.cases.priority import assign_priority
from agents_factory.modules.cases.repository import CaseRepository
from agents_factory.modules.cases.state_machine import (
    INTAKE_STATES,
    TERMINAL,
    validate_transition,
)
from agents_factory.modules.cases.targets import target_status, target_times


def require_backend(context: TenantContext) -> None:
    if context.actor_id is None or context.actor_type not in {
        "system",
        "platform_admin",
    }:
        raise ClaimCaseConflict("backend_actor_required")


def merge_provenance(
    previous: CaseRecord, submission: CaseSubmission
) -> dict[str, object]:
    if previous.capability != "returns_claims":
        return submission.intake
    old = PreparedClaimIntake.model_validate(previous.intake)
    new = PreparedClaimIntake.model_validate(submission.intake)
    contributions = {item.message_id: item for item in old.contributions}
    for item in new.contributions:
        if item.message_id in contributions and contributions[item.message_id] != item:
            raise ClaimCaseConflict("case_message_replay_conflict")
        contributions[item.message_id] = item
    if len(contributions) > 1000:
        raise ClaimCaseConflict("case_intake_limit_requires_review")
    return new.model_copy(
        update={"contributions": tuple(contributions.values())}
    ).model_dump(mode="json")


class CaseService:
    """Independent transactions survive an outer Action rollback.

    Internal API only. Intake adapters run behind confirmed Actions. Backoffice
    transitions change case bookkeeping; they NEVER authorize a provider action.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        policies: Mapping[UUID, CasePolicy] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions = sessions
        self.policies = dict(policies or {})
        self.now = now or (lambda: datetime.now(UTC))

    @asynccontextmanager
    async def transaction(
        self, context: TenantContext
    ) -> AsyncIterator[CaseRepository]:
        require_backend(context)
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await set_tenant_context(session, context.tenant_id)
            yield CaseRepository(session, context)

    async def get(
        self, *, context: TenantContext, customer_ref: str, case_id: UUID
    ) -> CaseRecord | None:
        async with self.transaction(context) as repo:
            return await repo.get(case_id, customer_ref)

    async def status(
        self, *, context: TenantContext, customer_ref: str, case_id: UUID
    ) -> CustomerCaseStatus | None:
        case = await self.get(
            context=context, customer_ref=customer_ref, case_id=case_id
        )
        return (
            CustomerCaseStatus(
                case_id=case.id,
                status=case.status,
                customer_result=case.customer_result,
            )
            if case
            else None
        )

    async def history(
        self, *, context: TenantContext, customer_ref: str, case_id: UUID
    ) -> tuple[CaseEvent, ...]:
        async with self.transaction(context) as repo:
            if await repo.get(case_id, customer_ref) is None:
                raise ClaimCaseConflict("case_unavailable")
            return await repo.history(case_id)

    async def find_open(
        self, *, context: TenantContext, customer_ref: str, deduplication_key: str
    ) -> CaseRecord | None:
        async with self.transaction(context) as repo:
            case = await repo.equivalent(customer_ref, deduplication_key)
            # Lookup remains read-only, including at the close boundary.
            if (
                case is not None
                and case.status == "RESOLVED"
                and case.close_at is not None
                and self.now() >= case.close_at
            ):
                return None
            return case

    async def _schedule(self, repo: CaseRepository, case: CaseRecord) -> None:
        instants = (
            (case.close_at,)
            if case.status == "RESOLVED"
            else (case.approaching_at, case.target_at)
        )
        for instant in instants:
            if instant is None:
                continue
            await OutboxService(repo.session).enqueue(
                context=repo.context,
                idempotency_key=f"case-timer:{case.id}:{instant.isoformat()}",
                topic="cases.timer",
                payload={"aggregate_id": str(case.id)},
                available_at=instant,
            )

    async def _evidence(self, repo: CaseRepository, submission: CaseSubmission) -> None:
        for evidence_id in submission.evidence_ids:
            allowed = await repo.session.scalar(
                text(
                    "SELECT id FROM public.media_evidence WHERE tenant_id=:tenant AND id=:id AND customer_ref=:customer AND status IN ('READY','PENDING_PROVIDER','HUMAN_REVIEW') AND scan_status='CLEAN' AND content_digest IS NOT NULL AND deleted_at IS NULL AND expires_at>:now"
                ),
                {
                    "tenant": repo.context.tenant_id,
                    "id": evidence_id,
                    "customer": submission.customer_ref,
                    "now": self.now(),
                },
            )
            if allowed is None:
                raise ClaimCaseConflict("case_evidence_unavailable")

    def _new(self, submission: CaseSubmission) -> CaseRecord:
        policy = self.policies.get(submission.tenant_id, CasePolicy()).model_copy(
            deep=True
        )
        priority, now = assign_priority(submission.issue_type, policy), self.now()
        approaching_at, target_at = target_times(now, priority, policy)
        fields = submission.model_dump(exclude={"initial_status", "evidence_ids"})
        return CaseRecord(
            **fields,
            id=new_uuid7(),
            revision=1,
            status=submission.initial_status,
            priority=priority,
            policy=policy,
            approaching_at=approaching_at,
            target_at=target_at,
            created_at=now,
            updated_at=now,
        )

    async def find_or_create(
        self,
        *,
        context: TenantContext,
        submission: CaseSubmission,
        operation_id: UUID,
        parameter_digest: str,
        expected_revision: int | None = None,
        case_id: UUID | None = None,
    ) -> CaseRecord:
        if (
            submission.tenant_id != context.tenant_id
            or submission.deduplication_key
            != case_key(
                context.tenant_id,
                submission.customer_ref,
                submission.capability,
                submission.issue_type,
                submission.binding_id,
                submission.resource_id,
            )
        ):
            raise ClaimCaseConflict("case_scope_mismatch")
        digest = NormalizedParameters.from_value(
            {
                "operation": "intake",
                "parameter_digest": parameter_digest,
                "submission": submission.model_dump(mode="json"),
                "expected_revision": expected_revision,
                "case_id": str(case_id) if case_id else None,
            }
        ).digest
        async with self.transaction(context) as repo:
            # Global order: operation lock -> equivalence lock -> case row lock.
            await repo.lock("operation", str(operation_id))
            replay = await repo.replay(operation_id, digest, submission.customer_ref)
            if replay is not None:
                return replay
            await repo.lock("dedupe", submission.deduplication_key)
            await self._evidence(repo, submission)
            previous = await repo.equivalent(
                submission.customer_ref, submission.deduplication_key
            )
            if (
                previous is not None
                and previous.status == "RESOLVED"
                and previous.close_at is not None
                and self.now() >= previous.close_at
            ):
                await self._change(repo, previous, "CLOSED", "reopen_window_elapsed")
                previous = None
            if case_id is not None and (previous is None or case_id != previous.id):
                raise ClaimCaseConflict("case_changed_requires_review")
            if previous is None:
                if expected_revision not in (None, 0):
                    raise ClaimCaseConflict("case_changed_requires_review")
                case = self._new(submission)
                await repo.save(case, new=True)
                await self._schedule(repo, case)
            else:
                case = previous
                if expected_revision is not None:
                    if previous.status not in INTAKE_STATES:
                        raise ClaimCaseConflict("case_requires_backoffice")
                    if (
                        previous.content_digest != submission.content_digest
                        and expected_revision != previous.revision
                    ):
                        raise ClaimCaseConflict("case_changed_requires_review")
                    # Identical semantic content reuses the revision, retaining
                    # incremental message provenance without invalidating delivery.
                    changed = previous.content_digest != submission.content_digest
                    if not changed and previous.status != submission.initial_status:
                        raise ClaimCaseConflict("case_requires_backoffice")
                    case = previous.model_copy(
                        update={
                            "intake": merge_provenance(previous, submission),
                            "content_digest": submission.content_digest,
                            "status": submission.initial_status,
                            "revision": previous.revision + int(changed),
                            "updated_at": self.now(),
                        }
                    )
                    await repo.save(case)
                # Legacy Orders API has no CAS: reuse, never overwrite newer facts.
            await repo.event(
                case,
                event_type="CREATED"
                if previous is None
                else "INTAKE_REUSED"
                if case.revision == previous.revision
                else "INTAKE_UPDATED",
                reason="confirmed_customer_intake",
                previous=previous,
                action_reference=operation_id,
                evidence_ids=submission.evidence_ids,
            )
            await repo.receipt(operation_id, digest, case)
            return case

    async def _change(
        self,
        repo: CaseRepository,
        case: CaseRecord,
        target: CaseStatus,
        reason: str,
        *,
        action_reference: UUID | None = None,
        approval_reference: str | None = None,
        customer_result: str | None = None,
    ) -> CaseRecord:
        validate_transition(case.status, target)
        now = self.now()
        changes: dict[str, object] = {
            "status": target,
            "revision": case.revision + 1,
            "updated_at": now,
        }
        if target == "RESOLVED":
            changes.update(
                resolved_at=now,
                close_at=now + timedelta(hours=case.policy.close_after_hours),
            )
        elif target == "REOPENED":
            approaching_at, target_at = target_times(now, case.priority, case.policy)
            changes.update(
                resolved_at=None,
                close_at=None,
                customer_result=None,
                result_recorded_by=None,
                approaching_at=approaching_at,
                target_at=target_at,
                target_status="ON_TRACK",
            )
        if customer_result is not None:
            changes.update(
                customer_result=customer_result,
                result_recorded_by=repo.context.actor_id,
            )
        updated = CaseRecord.model_validate(case.model_dump() | changes)
        await repo.save(updated)
        await repo.event(
            updated,
            previous=case,
            event_type="STATE_CHANGED",
            reason=reason,
            action_reference=action_reference,
            approval_reference=approval_reference,
        )
        if target in {"RESOLVED", "REOPENED"}:
            await self._schedule(repo, updated)
        return updated

    async def transition(
        self,
        *,
        context: TenantContext,
        customer_ref: str,
        case_id: UUID,
        command: CaseTransition,
    ) -> CaseRecord:
        if context.actor_type != "platform_admin" or not command.reason.strip():
            raise ClaimCaseConflict("backoffice_actor_and_reason_required")
        if command.target in {"REOPENED", "CLOSED"}:
            raise ClaimCaseConflict("use_case_reopen_or_timer")
        if command.customer_result is not None and command.target not in {
            "RESOLVED",
            "REJECTED",
        }:
            raise ClaimCaseConflict("case_result_requires_decision")
        digest = NormalizedParameters.from_value(
            {
                "operation": "transition",
                "case_id": str(case_id),
                "command": command.model_dump(mode="json"),
            }
        ).digest
        async with self.transaction(context) as repo:
            await repo.lock("operation", str(command.operation_id))
            replay = await repo.replay(command.operation_id, digest, customer_ref)
            if replay is not None:
                return replay
            case = await repo.get(case_id, customer_ref, locked=True)
            if case is None or case.revision != command.expected_revision:
                raise ClaimCaseConflict("case_changed_requires_review")
            if (
                case.status == "PENDING_APPROVAL"
                and command.target in {"IN_PROGRESS", "REJECTED"}
                and command.approval_reference is None
            ):
                raise ClaimCaseConflict("case_approval_reference_required")
            updated = await self._change(
                repo,
                case,
                command.target,
                command.reason,
                action_reference=command.action_reference,
                approval_reference=command.approval_reference,
                customer_result=command.customer_result,
            )
            await repo.receipt(command.operation_id, digest, updated)
            return updated

    async def report_persisting_issue(
        self,
        *,
        context: TenantContext,
        customer_ref: str,
        case_id: UUID,
        operation_id: UUID,
        reason: str,
    ) -> CaseRecord:
        if not reason.strip() or len(reason) > 1000:
            raise ClaimCaseConflict("case_reason_required")
        digest = NormalizedParameters.from_value(
            {"operation": "issue_persists", "case_id": str(case_id), "reason": reason}
        ).digest
        async with self.transaction(context) as repo:
            await repo.lock("operation", str(operation_id))
            replay = await repo.replay(operation_id, digest, customer_ref)
            if replay is not None:
                return replay
            prior = await repo.get(case_id, customer_ref)
            if prior is None:
                raise ClaimCaseConflict("case_unavailable")
            await repo.lock("dedupe", prior.deduplication_key)
            case = await repo.get(case_id, customer_ref, locked=True)
            assert case is not None
            if (
                case.status == "RESOLVED"
                and case.close_at is not None
                and self.now() < case.close_at
            ):
                updated = await self._change(
                    repo, case, "REOPENED", reason, action_reference=operation_id
                )
            elif case.status == "CLOSED" or (
                case.status == "RESOLVED"
                and case.close_at is not None
                and self.now() >= case.close_at
            ):
                if case.status == "RESOLVED":
                    await self._change(repo, case, "CLOSED", "reopen_window_elapsed")
                active = await repo.equivalent(customer_ref, case.deduplication_key)
                if active is not None:
                    updated = active
                else:
                    submission = CaseSubmission(
                        **{
                            key: getattr(case, key)
                            for key in CaseSubmission.model_fields
                            if key not in {"initial_status", "evidence_ids"}
                        },
                        initial_status="OPEN",
                    )
                    updated = self._new(submission)
                    await repo.save(updated, new=True)
                    await repo.event(
                        updated,
                        event_type="CREATED",
                        reason=f"related_closed_case:{case.id}; {reason}",
                        action_reference=operation_id,
                    )
                    await self._schedule(repo, updated)
            elif case.status not in TERMINAL:
                updated = case
            else:
                raise ClaimCaseConflict("case_not_reopenable")
            await repo.receipt(operation_id, digest, updated)
            return updated

    async def record_customer_response(
        self,
        *,
        context: TenantContext,
        customer_ref: str,
        case_id: UUID,
        operation_id: UUID,
        issue_persists: bool,
        reason: str,
    ) -> CaseRecord:
        """Trusted inbound/backoffice report, not a status-read side effect."""
        if issue_persists:
            return await self.report_persisting_issue(
                context=context,
                customer_ref=customer_ref,
                case_id=case_id,
                operation_id=operation_id,
                reason=reason,
            )
        if not reason.strip() or len(reason) > 1000:
            raise ClaimCaseConflict("case_reason_required")
        digest = NormalizedParameters.from_value(
            {
                "operation": "customer_response",
                "case_id": str(case_id),
                "reason": reason,
            }
        ).digest
        async with self.transaction(context) as repo:
            await repo.lock("operation", str(operation_id))
            replay = await repo.replay(operation_id, digest, customer_ref)
            if replay is not None:
                return replay
            case = await repo.get(case_id, customer_ref, locked=True)
            if case is None:
                raise ClaimCaseConflict("case_unavailable")
            if (
                case.status == "RESOLVED"
                and case.close_at is not None
                and self.now() < case.close_at
            ):
                # Silence window restarts, resolution time/history stays intact.
                updated = case.model_copy(
                    update={
                        "close_at": self.now()
                        + timedelta(hours=case.policy.close_after_hours),
                        "updated_at": self.now(),
                        "revision": case.revision + 1,
                    }
                )
                await repo.save(updated)
                await self._schedule(repo, updated)
            else:
                updated = case
            await repo.event(
                updated,
                previous=case,
                event_type="CUSTOMER_RESPONSE",
                reason=reason,
                action_reference=operation_id,
            )
            await repo.receipt(operation_id, digest, updated)
            return updated

    async def process_timer(self, *, context: TenantContext, case_id: UUID) -> None:
        async with self.transaction(context) as repo:
            row = (
                (
                    await repo.session.execute(
                        text(
                            "SELECT * FROM public.cases WHERE tenant_id=:tenant AND id=:id FOR UPDATE"
                        ),
                        {"tenant": context.tenant_id, "id": case_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return
            case = CaseRecord.model_validate(dict(row))
            if case.status == "RESOLVED":
                if case.close_at is not None and self.now() >= case.close_at:
                    await self._change(repo, case, "CLOSED", "reopen_window_elapsed")
                return
            if case.status in TERMINAL:
                return
            status = target_status(
                self.now(), approaching_at=case.approaching_at, target_at=case.target_at
            )
            if status == case.target_status or status == "ON_TRACK":
                return
            updated = case.model_copy(
                update={"target_status": status, "updated_at": self.now()}
            )
            await repo.save(updated)
            await repo.event(
                updated,
                previous=case,
                event_type="RESPONSE_TARGET_ALERT",
                reason=status,
            )
            await AuditService(repo.session).record(
                context=context,
                event_type="cases.response_target_alert",
                entity_type="case",
                entity_id=case.id,
                payload={"priority": case.priority, "target_status": status},
            )
