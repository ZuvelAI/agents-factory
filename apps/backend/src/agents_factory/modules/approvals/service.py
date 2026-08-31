from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context
from agents_factory.modules.actions.models import ActionRecord
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.approvals.models import (
    ApprovalDecision,
    ApprovalError,
    ApprovalLink,
    ApprovalRequest,
    ApprovalRoute,
    ApprovalRouteDraft,
    ApprovalState,
    DecideInput,
    MailState,
    OTPInput,
    OTPReceipt,
    PublicReceipt,
    ReviewDetails,
    ReviewReceipt,
    VerifyInput,
)
from agents_factory.modules.approvals.otp import issue_otp, verify_otp
from agents_factory.modules.approvals.repository import ApprovalRepository
from agents_factory.modules.approvals.routes import validate_route_action
from agents_factory.modules.approvals.tokens import (
    ApprovalProofs,
    LinkClaims,
    token_digest,
)
from agents_factory.modules.integrations.google.approval_mailer import ApprovalMailer
from agents_factory.modules.secrets.redaction import ResolvedSecret


@dataclass(frozen=True)
class LockedApproval:
    repository: ApprovalRepository
    request: ApprovalRequest
    route: ApprovalRoute
    action: ActionRecord


def require_backend(context: TenantContext, *, admin_only: bool = False) -> None:
    if context.actor_id is None or context.actor_type not in (
        {"platform_admin"} if admin_only else {"system", "platform_admin"}
    ):
        raise ApprovalError("approval_backend_actor_required", status=403)


class ApprovalService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        proofs: ApprovalProofs,
        mailer: ApprovalMailer,
        public_origin: str,
        now: Callable[[], datetime] | None = None,
        retain_network_fingerprints: bool = False,
    ) -> None:
        parsed = urlsplit(public_origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.port not in {None, 443}
        ):
            raise ValueError("approval page requires a configured HTTPS origin")
        self.sessions, self.proofs, self.mailer = sessions, proofs, mailer
        self.public_origin = public_origin.rstrip("/")
        self.now = now or (lambda: datetime.now(UTC))
        self.retain_network_fingerprints = retain_network_fingerprints

    @asynccontextmanager
    async def transaction(
        self, context: TenantContext
    ) -> AsyncIterator[ApprovalRepository]:
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await set_tenant_context(session, context.tenant_id)
            yield ApprovalRepository(session, context)

    async def save_route(
        self,
        *,
        context: TenantContext,
        configuration: ApprovalRouteDraft,
        expected_revision: int = 0,
    ) -> ApprovalRoute:
        require_backend(context, admin_only=True)
        validate_route_action(configuration)
        if configuration.enabled and not self.mailer.supports(
            context.tenant_id, configuration.authorized_emails
        ):
            raise ApprovalError("approval_mailbox_not_configured")
        async with self.transaction(context) as repo:
            key = int.from_bytes(
                hashlib.sha256(
                    f"approval-route:{context.tenant_id}:{configuration.ref}:{configuration.action}".encode()
                ).digest()[:8],
                "big",
                signed=True,
            )
            await repo.session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": key}
            )
            old = await repo.route(
                ref=configuration.ref,
                capability=configuration.capability,
                action=configuration.action,
                lock=" FOR UPDATE",
            )
            if old is not None and old.configuration == configuration:
                return old
            if (old.revision if old else 0) != expected_revision:
                raise ApprovalError("approval_route_revision_conflict")
            route = ApprovalRoute(
                id=old.id if old else new_uuid7(),
                tenant_id=context.tenant_id,
                revision=expected_revision + 1,
                configuration=configuration,
                digest=configuration.digest,
            )
            await repo.save_route(route, new=old is None)
            await AuditService(repo.session).record(
                context=context,
                event_type="approval.route_configured",
                entity_type="approval_route",
                entity_id=route.id,
                payload={"revision": route.revision, "digest": route.digest},
            )
            return route

    async def request(
        self, *, context: TenantContext, action_id: UUID
    ) -> ApprovalRequest:
        """Call AFTER customer confirmation commits. No email/provider call here."""
        require_backend(context)
        async with self.transaction(context) as repo:
            action = await ActionRepository(repo.session, context).get(
                action_id, lock=True
            )
            if action is None:
                raise ApprovalError()
            existing = await repo.request(action_id=action_id)
            if existing is not None:
                if existing.parameter_digest != action.parameter_digest:
                    raise ApprovalError("approval_action_changed")
                return existing
            route = await repo.route(
                ref=action.approval_route_ref or "",
                capability=action.capability,
                action=action.action_type,
                lock=" FOR SHARE",
            )
            if route is None or not route.configuration.enabled:
                raise ApprovalError("approval_route_required")
            if not self.mailer.supports(
                context.tenant_id, route.configuration.authorized_emails
            ):
                raise ApprovalError("approval_mailbox_not_configured")
            now = self.now()
            confirmed_digest = hashlib.sha256(
                f"{action.id}:{action.customer_ref}:{action.parameter_digest}:confirmed".encode()
            ).hexdigest()
            if not self._action_matches(action, route) or (
                action.confirmation_required
                and (
                    action.confirmed_at is None
                    or action.confirmation_expires_at is None
                    or action.confirmed_at >= action.confirmation_expires_at
                    or now >= action.confirmation_expires_at
                    or action.confirmation_digest is None
                    or not hmac.compare_digest(
                        action.confirmation_digest, confirmed_digest
                    )
                )
            ):
                raise ApprovalError("confirmed_approval_action_required")
            expiry = datetime.fromtimestamp(
                int(
                    (
                        now + timedelta(minutes=route.configuration.expires_minutes)
                    ).timestamp()
                ),
                UTC,
            )
            request = ApprovalRequest(
                id=new_uuid7(),
                tenant_id=context.tenant_id,
                action_id=action.id,
                parameter_digest=action.parameter_digest,
                route_id=route.id,
                route_digest=route.digest,
                state="PENDING",
                created_at=now,
                expires_at=expiry,
            )
            await repo.insert_request(request)
            for email in route.configuration.authorized_emails:
                link_id = new_uuid7()
                claims = LinkClaims(context.tenant_id, request.id, link_id, expiry)
                value = self.proofs.issue_link(claims)
                await repo.save_link(
                    ApprovalLink(
                        id=link_id,
                        tenant_id=context.tenant_id,
                        request_id=request.id,
                        email=email,
                        token_digest=token_digest(value.reveal().decode()),
                    ),
                    new=True,
                )
            for kind, at in (("approvals.notify", now), ("approvals.expire", expiry)):
                await OutboxService(repo.session).enqueue(
                    context=context,
                    idempotency_key=f"{kind}:{request.id}",
                    topic=kind,
                    payload={"aggregate_id": str(request.id)},
                    available_at=at,
                )
            await AuditService(repo.session).record(
                context=context,
                event_type="approval.requested",
                entity_type="approval_request",
                entity_id=request.id,
                payload={
                    "action_id": str(action.id),
                    "parameter_digest": action.parameter_digest,
                    "route_digest": route.digest,
                },
            )
            return request

    @staticmethod
    def _action_matches(action: ActionRecord, route: ApprovalRoute) -> bool:
        return bool(
            action.state == "AWAITING_APPROVAL"
            and action.approval_required
            and action.approval_route_ref == route.configuration.ref
            and action.capability == route.configuration.capability
            and action.action_type == route.configuration.action
            and action.achieved_identity_level >= action.required_identity_level
        )

    @asynccontextmanager
    async def locked(
        self, context: TenantContext, request_id: UUID
    ) -> AsyncIterator[LockedApproval | None]:
        async with self.transaction(context) as repo:
            snapshot = await repo.request(request_id=request_id)
            if snapshot is None:
                yield None
                return
            # One ordering across request, OTP, expiry, notice and decision paths:
            # Action -> Route (share) -> Request -> child links.
            action = await ActionRepository(repo.session, context).get(
                snapshot.action_id, lock=True
            )
            route = await repo.route(route_id=snapshot.route_id, lock=" FOR SHARE")
            request = await repo.request(request_id=request_id, locked=True)
            if action is None or route is None or request is None:
                yield None
                return
            yield LockedApproval(repo, request, route, action)

    async def _close(self, locked: LockedApproval, state: ApprovalState) -> None:
        repo, request = locked.repository, locked.request
        now = self.now()
        await repo.session.execute(
            text(
                "UPDATE public.approval_requests SET state=:state,closed_at=:now WHERE tenant_id=:tenant AND id=:id AND state='PENDING'"
            ),
            {"state": state, "now": now, "tenant": request.tenant_id, "id": request.id},
        )
        await repo.session.execute(
            text(
                "UPDATE public.approval_links SET invalidated_at=:now,otp_digest=NULL WHERE tenant_id=:tenant AND request_id=:request"
            ),
            {"now": now, "tenant": request.tenant_id, "request": request.id},
        )
        if (
            state in {"REJECTED", "EXPIRED"}
            and locked.action.state == "AWAITING_APPROVAL"
        ):
            await ActionRepository(repo.session, repo.context).transition(
                action=locked.action,
                target="REJECTED" if state == "REJECTED" else "EXPIRED",
                event_type=f"action.approval_{state.lower()}",
                payload={"approval_request_id": str(request.id)},
                changed_at=now,
            )
        await AuditService(repo.session).record(
            context=repo.context,
            event_type=f"approval.{state.lower()}",
            entity_type="approval_request",
            entity_id=request.id,
            payload={"state": state},
        )

    async def _usable(self, locked: LockedApproval | None) -> bool:
        if locked is None or locked.request.state != "PENDING":
            return False
        if self.now() >= locked.request.expires_at:
            await self._close(locked, "EXPIRED")
            return False
        if (
            not locked.route.configuration.enabled
            or locked.route.digest != locked.request.route_digest
            or not self._action_matches(locked.action, locked.route)
            or locked.action.parameter_digest != locked.request.parameter_digest
        ):
            await self._close(locked, "INVALIDATED")
            return False
        return True

    def _public_context(self, raw_token: str) -> tuple[LinkClaims, TenantContext]:
        claims = self.proofs.verify_link(raw_token)
        return claims, TenantContext(
            claims.tenant_id, claims.link_id, "approver", new_uuid7()
        )

    async def _link(
        self, locked: LockedApproval, claims: LinkClaims, raw_token: str
    ) -> ApprovalLink | None:
        link = await locked.repository.link(claims.request_id, claims.link_id)
        if (
            link is None
            or link.invalidated_at is not None
            or claims.expires_at != locked.request.expires_at
            or not hmac.compare_digest(token_digest(raw_token), link.token_digest)
            or link.email not in locked.route.configuration.authorized_emails
        ):
            return None
        return link

    async def inspect(self, raw_token: str) -> PublicReceipt:
        claims, context = self._public_context(raw_token)
        async with self.locked(context, claims.request_id) as locked:
            if not await self._usable(locked):
                return PublicReceipt(status="CLOSED")
            assert locked is not None
            link = await self._link(locked, claims, raw_token)
            return PublicReceipt(status="OPEN" if link is not None else "CLOSED")

    async def _send(
        self,
        context: TenantContext,
        *,
        recipient: str,
        subject: str,
        body: ResolvedSecret,
        delivery_id: UUID,
    ) -> MailState:
        try:
            status = await self.mailer.send(
                context=replace(context, actor_type="system"),
                recipient=recipient,
                subject=subject,
                body=body,
                delivery_id=delivery_id,
            )
            return status if status in {"SENT", "FAILED", "UNCERTAIN"} else "UNCERTAIN"
        except Exception:
            return "UNCERTAIN"

    async def send_notices(self, *, context: TenantContext, request_id: UUID) -> None:
        require_backend(context)
        async with self.transaction(context) as repo:
            ids = [link.id for link in await repo.links(request_id)]
        for link_id in ids:
            async with self.locked(context, request_id) as locked:
                if not await self._usable(locked):
                    return
                assert locked is not None
                link = await locked.repository.link(request_id, link_id)
                if link is None or link.invalidated_at is not None:
                    continue
                if link.notice_state == "CLAIMED":
                    await locked.repository.save_link(
                        link.model_copy(update={"notice_state": "UNCERTAIN"})
                    )
                    continue
                if link.notice_state != "PENDING":
                    continue
                await locked.repository.save_link(
                    link.model_copy(update={"notice_state": "CLAIMED"})
                )
                claims = LinkClaims(
                    context.tenant_id, request_id, link_id, locked.request.expires_at
                )
                value = self.proofs.issue_link(claims).reveal().decode()
                if token_digest(value) != link.token_digest:
                    raise ApprovalError()
                # The secret is in the URL fragment, absent from HTTP paths,
                # reverse-proxy access logs and Referrer. Task 32 consumes it.
                url = f"{self.public_origin}/approval/review#token={value}"
                body = ResolvedSecret(
                    (
                        f"Revisión requerida: {locked.action.action_type}\n"
                        f"Solicitud: {request_id}\nVence: {locked.request.expires_at.isoformat()}\n"
                        f"Abre el enlace temporal y verifica tu correo para decidir:\n{url}\n"
                        "Este aviso no autoriza ni ejecuta la operación."
                    ).encode()
                )
            status = await self._send(
                context,
                recipient=link.email,
                subject="Agents Factory: revisión pendiente",
                body=body,
                delivery_id=link_id,
            )
            async with self.transaction(context) as repo:
                await repo.session.execute(
                    text(
                        "UPDATE public.approval_links SET notice_state=:state WHERE tenant_id=:tenant AND id=:id AND notice_state='CLAIMED'"
                    ),
                    {"state": status, "tenant": context.tenant_id, "id": link_id},
                )

    async def start_otp(self, command: OTPInput) -> OTPReceipt:
        raw = command.link_token.get_secret_value()
        claims, context = self._public_context(raw)
        # The response shape doesn't confirm membership in an email allowlist.
        receipt = OTPReceipt(challenge_id=new_uuid7())
        async with self.locked(context, claims.request_id) as locked:
            if not await self._usable(locked):
                return receipt
            assert locked is not None
            link = await self._link(locked, claims, raw)
            policy, now = locked.route.configuration, self.now()
            if (
                link is None
                or link.email != command.email
                or link.otp_attempts >= policy.otp_max_attempts
                or link.otp_sends >= policy.otp_max_sends
            ):
                return receipt
            if link.last_sent_at is not None and now < link.last_sent_at + timedelta(
                seconds=policy.otp_cooldown_seconds
            ):
                return OTPReceipt(
                    challenge_id=link.challenge_id or receipt.challenge_id
                )
            issued = issue_otp(self.proofs, receipt.challenge_id)
            updated = link.model_copy(
                update={
                    "challenge_id": receipt.challenge_id,
                    "otp_digest": issued.digest,
                    "otp_expires_at": min(
                        locked.request.expires_at,
                        now + timedelta(seconds=policy.otp_seconds),
                    ),
                    "otp_sends": link.otp_sends + 1,
                    "last_sent_at": now,
                    "otp_delivery": "CLAIMED",
                }
            )
            await locked.repository.save_link(updated)
            await AuditService(locked.repository.session).record(
                context=context,
                event_type="approval.otp_requested",
                entity_type="approval_request",
                entity_id=claims.request_id,
                payload={
                    "link_id": str(link.id),
                    "challenge_id": str(receipt.challenge_id),
                },
            )
        body = ResolvedSecret(
            (
                f"Código de verificación: {issued.plaintext.reveal().decode()}\n"
                f"Solicitud: {claims.request_id}\nVálido por hasta {policy.otp_seconds} segundos.\n"
                "No compartas este código. Solo verifica el correo; la decisión requiere tu confirmación."
            ).encode()
        )
        status = await self._send(
            context,
            recipient=link.email,
            subject="Agents Factory: código de verificación",
            body=body,
            delivery_id=receipt.challenge_id,
        )
        async with self.transaction(context) as repo:
            await repo.session.execute(
                text(
                    "UPDATE public.approval_links SET otp_delivery=:state WHERE tenant_id=:tenant AND id=:id AND challenge_id=:challenge AND otp_delivery='CLAIMED'"
                ),
                {
                    "state": status,
                    "tenant": context.tenant_id,
                    "id": link.id,
                    "challenge": receipt.challenge_id,
                },
            )
        return receipt

    async def _verified_link(
        self, locked: LockedApproval, claims: LinkClaims, raw: str, command: VerifyInput
    ) -> ApprovalLink | None:
        link = await self._link(locked, claims, raw)
        if link is None or link.email != command.email:
            return None
        policy, now = locked.route.configuration, self.now()
        if link.otp_attempts >= policy.otp_max_attempts:
            return None
        valid = bool(
            link.challenge_id == command.challenge_id
            and link.otp_digest is not None
            and link.otp_expires_at is not None
            and now < link.otp_expires_at
            and link.otp_delivery == "SENT"
            and verify_otp(
                self.proofs,
                command.challenge_id,
                command.code.get_secret_value(),
                link.otp_digest,
            )
        )
        if valid:
            return link
        attempts = link.otp_attempts + 1
        await locked.repository.save_link(
            link.model_copy(
                update={
                    "otp_attempts": attempts,
                    "invalidated_at": now
                    if attempts >= policy.otp_max_attempts
                    else None,
                    "otp_digest": None
                    if attempts >= policy.otp_max_attempts
                    else link.otp_digest,
                }
            )
        )
        await AuditService(locked.repository.session).record(
            context=locked.repository.context,
            event_type="approval.verification_failed",
            entity_type="approval_request",
            entity_id=claims.request_id,
            payload={"link_id": str(link.id), "attempt": attempts},
        )
        return None

    async def review(self, command: VerifyInput) -> ReviewReceipt:
        raw = command.link_token.get_secret_value()
        claims, context = self._public_context(raw)
        async with self.locked(context, claims.request_id) as locked:
            if not await self._usable(locked):
                return ReviewReceipt(status="CLOSED")
            assert locked is not None
            link = await self._verified_link(locked, claims, raw, command)
            if link is None:
                return ReviewReceipt(status="INVALID_VERIFICATION")
            # Only a verified reviewer sees bounded identifiers, never the complete
            # Action parameters, contact details or raw connector/provider data.
            reference = locked.action.parameters.get(
                "order_id" if locked.action.capability == "orders" else "appointment_id"
            )
            safe_reference = (
                str(reference)
                if isinstance(reference, (str, int))
                and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(reference))
                else None
            )
            assert link.otp_expires_at is not None
            return ReviewReceipt(
                status="OPEN",
                details=ReviewDetails(
                    request_id=locked.request.id,
                    action=locked.action.action_type,
                    resource_reference=safe_reference,
                    expires_at=min(locked.request.expires_at, link.otp_expires_at),
                ),
            )

    async def decide(
        self,
        command: DecideInput,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> PublicReceipt:
        raw = command.link_token.get_secret_value()
        claims, context = self._public_context(raw)
        async with self.locked(context, claims.request_id) as locked:
            if not await self._usable(locked):
                return PublicReceipt(status="CLOSED")
            assert locked is not None
            link = await self._verified_link(locked, claims, raw, command)
            if link is None:
                return PublicReceipt(status="INVALID_VERIFICATION")
            now = self.now()
            decision = ApprovalDecision(
                id=new_uuid7(),
                tenant_id=context.tenant_id,
                request_id=claims.request_id,
                action_id=locked.action.id,
                parameter_digest=locked.action.parameter_digest,
                approver_email=link.email,
                decision=command.decision,
                requested_result=command.requested_result,
                decided_at=now,
                metadata=self.proofs.audit_metadata(
                    tenant_id=context.tenant_id, at=now, ip=ip, user_agent=user_agent
                )
                if self.retain_network_fingerprints
                else {},
            )
            await locked.repository.insert_decision(decision)
            await self._close(
                locked, "APPROVED" if command.decision == "APPROVE" else "REJECTED"
            )
            if command.decision == "APPROVE":
                await OutboxService(locked.repository.session).enqueue(
                    context=context,
                    idempotency_key=f"approvals.execute:{claims.request_id}",
                    topic="approvals.execute",
                    payload={
                        "aggregate_id": str(locked.action.id),
                        "approval_request_id": str(claims.request_id),
                        "approval_reference": str(decision.id),
                        "parameter_digest": decision.parameter_digest,
                    },
                )
            # No Action execution, customer notification or raw decision metadata
            # crosses the public endpoint. Task 33 revalidates before execution.
            return PublicReceipt(status="RECORDED")

    async def expire(self, *, context: TenantContext, request_id: UUID) -> None:
        require_backend(context)
        async with self.locked(context, request_id) as locked:
            await self._usable(locked)

    async def get(
        self, *, context: TenantContext, request_id: UUID
    ) -> ApprovalRequest | None:
        require_backend(context)
        async with self.transaction(context) as repo:
            return await repo.request(request_id=request_id)


class PersistedApprovalVerifier:
    """Read-only ActionService port. A reference alone never authorizes execution."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: TenantContext,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        require_backend(context)
        self.sessions, self.context = sessions, context
        self.now = now or (lambda: datetime.now(UTC))

    async def verify(
        self,
        *,
        route_ref: str,
        approval_reference: str,
        action_id: UUID,
        parameter_digest: str,
    ) -> bool:
        try:
            decision_id = UUID(approval_reference)
        except ValueError:
            return False
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await set_tenant_context(session, self.context.tenant_id)
            matched = await session.scalar(
                text(
                    "SELECT d.id FROM public.approval_decisions d JOIN public.approval_requests r ON (r.tenant_id=d.tenant_id AND r.id=d.request_id) JOIN public.approval_routes route ON (route.tenant_id=r.tenant_id AND route.id=r.route_id) WHERE d.tenant_id=:tenant AND d.id=:decision AND d.action_id=:action AND d.parameter_digest=:digest AND r.parameter_digest=:digest AND r.action_id=:action AND d.decision='APPROVE' AND r.state='APPROVED' AND r.expires_at>:now AND route.ref=:ref AND route.digest=r.route_digest AND route.configuration->>'enabled'='true'"
                ),
                {
                    "tenant": self.context.tenant_id,
                    "decision": decision_id,
                    "action": action_id,
                    "digest": parameter_digest,
                    "ref": route_ref,
                    "now": self.now(),
                },
            )
            return matched is not None
