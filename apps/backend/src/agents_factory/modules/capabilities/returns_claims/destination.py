from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import model_validator

from agents_factory.common.context import TenantContext
from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.cases.claims_contracts import ClaimCase
from agents_factory.modules.integrations.contracts import (
    Connector,
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.integrations.google.base import (
    GoogleBinding,
    GoogleHTTP,
    InputModel,
)
from agents_factory.modules.integrations.google.drive import DriveResource
from agents_factory.modules.integrations.google.factory import ConnectedGoogleConnector
from agents_factory.modules.integrations.google.gmail import GmailResource, Mailbox
from agents_factory.modules.integrations.google.sheets import SheetsResource
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.modules.media.contracts import BinaryMedia


QUEUE_FIELDS = frozenset(
    {
        "case_id",
        "revision",
        "status",
        "issue_type",
        "customer_ref",
        "order_reference",
        "description",
        "requested_resolution",
        "missing_fields",
        "evidence_ids",
        "review_flags",
    }
)


class GoogleClaimDestination(InputModel):
    tenant_id: UUID
    binding_id: UUID
    sheets_connection_id: UUID
    drive_connection_id: UUID
    gmail_connection_id: UUID
    sheets: SheetsResource
    drive: DriveResource
    gmail: GmailResource
    notify: Mailbox

    @model_validator(mode="after")
    def configured_destinations(self) -> Self:
        if (
            set(self.sheets.fields) != QUEUE_FIELDS
            or self.notify not in self.gmail.approval_recipients
        ):
            raise ValueError("claim destination mapping/recipient mismatch")
        return self

    @property
    def digest(self) -> str:
        value = self.model_dump(mode="json")
        value["drive"]["readable_file_ids"] = sorted(self.drive.readable_file_ids)
        value["gmail"]["approval_recipients"] = sorted(self.gmail.approval_recipients)
        return NormalizedParameters.from_value(value).digest


class ClaimDeliveryLedger(Protocol):
    """Durable Task 30 handoff dependency; NEVER replace with production memory.

    serialized must coordinate processes per tenant/destination/case. once commits
    a claim before the callback and a receipt independently of the outer Action.
    It compares the payload digest, replays terminal receipts, and maps abandoned
    in-flight claims to UNCERTAIN without another provider write. Preserve external
    file IDs for reconciliation and privacy/retention cleanup. Failed/uncertain
    effects need explicit operator reconciliation, not automatic resend.
    """

    @property
    def available(self) -> bool: ...

    def serialized(
        self, *, context: TenantContext, key: str
    ) -> AbstractAsyncContextManager[None]: ...

    async def once(
        self,
        *,
        context: TenantContext,
        key: str,
        digest: str,
        operation: str,
        effect: Callable[[], Awaitable[ConnectorResult]],
    ) -> ConnectorResult: ...


class ClaimEvidenceExport(Protocol):
    async def export_evidence(
        self, *, context: TenantContext, customer_ref: str, evidence_id: UUID
    ) -> BinaryMedia: ...


class ClaimDestination(Protocol):
    @property
    def available(self) -> bool: ...

    @property
    def digest(self) -> str: ...

    async def deliver(
        self, *, context: TenantContext, case: ClaimCase
    ) -> dict[str, str]: ...


Product = Literal["google_sheets", "google_drive", "gmail"]


@dataclass(frozen=True)
class NativeClaimGoogle:
    integrations: IntegrationService
    context: TenantContext
    http: GoogleHTTP

    def __call__(
        self, destination: GoogleClaimDestination, product: Product
    ) -> Connector:
        if destination.tenant_id != self.context.tenant_id:
            raise ValueError("claim_destination_scope_mismatch")
        resources: dict[
            Product,
            tuple[
                SheetsResource | DriveResource | GmailResource, UUID, tuple[str, ...]
            ],
        ] = {
            "google_sheets": (
                destination.sheets,
                destination.sheets_connection_id,
                ("sheets.read_rows", "sheets.append_row", "sheets.update_row"),
            ),
            "google_drive": (
                destination.drive,
                destination.drive_connection_id,
                ("drive.store_evidence",),
            ),
            "gmail": (
                destination.gmail,
                destination.gmail_connection_id,
                ("gmail.send_approval_notice",),
            ),
        }
        resource, connection_id, operations = resources[product]
        return ConnectedGoogleConnector(
            service=self.integrations,
            context=self.context,
            connection_id=connection_id,
            product=product,
            binding=GoogleBinding(
                destination.tenant_id, destination.binding_id, frozenset(operations)
            ),
            resource=resource,
            http=self.http,
        )


@dataclass(frozen=True)
class GoogleClaimsDelivery:
    configuration: GoogleClaimDestination
    connectors: Callable[[GoogleClaimDestination, Product], Connector]
    ledger: ClaimDeliveryLedger
    evidence: ClaimEvidenceExport

    @property
    def available(self) -> bool:
        return self.ledger.available

    @property
    def digest(self) -> str:
        return self.configuration.digest

    async def _call(
        self,
        product: Product,
        operation: str,
        arguments: dict[str, object],
        key: str | None = None,
    ) -> ConnectorResult:
        try:
            result = await self.connectors(self.configuration, product).execute(
                ConnectorRequest(
                    tenant_id=self.configuration.tenant_id,
                    binding_id=self.configuration.binding_id,
                    operation=operation,
                    arguments=arguments,
                    idempotency_key=key,
                )
            )
            if result.operation != operation:
                raise ValueError("claim_destination_result_mismatch")
            return result
        except Exception:
            return ConnectorResult(
                operation=operation,
                status="FAILED" if operation == "sheets.read_rows" else "UNCERTAIN",
                error_code="claim_destination_unavailable",
            )

    async def deliver(
        self, *, context: TenantContext, case: ClaimCase
    ) -> dict[str, str]:
        if (
            not self.available
            or context.actor_type not in {"system", "platform_admin"}
            or context.actor_id is None
            or context.tenant_id != self.configuration.tenant_id
            or case.intake.tenant_id != context.tenant_id
            or case.intake.binding_id != self.configuration.binding_id
        ):
            raise ValueError("claim_destination_scope_mismatch")
        root = f"claims:{self.configuration.binding_id}:{case.case_id}:{self.digest}"
        outcome: dict[str, str] = {}
        async with self.ledger.serialized(context=context, key=root):
            files: list[str] = []
            for evidence_id in case.intake.draft.evidence_ids:
                try:
                    original = await self.evidence.export_evidence(
                        context=context,
                        customer_ref=case.intake.customer_ref,
                        evidence_id=evidence_id,
                    )
                except Exception:
                    outcome["drive"] = "UNAVAILABLE"
                    return outcome
                key = f"{root}:evidence:{evidence_id}"
                arguments: dict[str, object] = {
                    "name": f"{case.case_id}-{evidence_id}",
                    "mime_type": original.media_type,
                    "content_base64": base64.b64encode(original.content).decode(),
                }
                fingerprint = NormalizedParameters.from_value(
                    {
                        "id": str(evidence_id),
                        "mime_type": original.media_type,
                        "content_digest": hashlib.sha256(original.content).hexdigest(),
                    }
                ).digest

                async def upload(
                    arguments: dict[str, object] = arguments, key: str = key
                ) -> ConnectorResult:
                    return await self._call(
                        "google_drive", "drive.store_evidence", arguments, key
                    )

                result = await self.ledger.once(
                    context=context,
                    key=key,
                    digest=fingerprint,
                    operation="drive.store_evidence",
                    effect=upload,
                )
                file_id = result.data.get("file_id")
                if (
                    result.status != "SUCCEEDED"
                    or not isinstance(file_id, str)
                    or not file_id
                ):
                    outcome["drive"] = (
                        result.status if result.status != "SUCCEEDED" else "UNCERTAIN"
                    )
                    return outcome
                files.append(file_id)
            outcome["drive"] = "SUCCEEDED" if files else "NOT_REQUIRED"
            values: dict[str, object] = {
                "case_id": str(case.case_id),
                "revision": case.revision,
                "status": case.status,
                "issue_type": case.intake.draft.issue_type,
                "customer_ref": case.intake.customer_ref,
                "order_reference": case.intake.draft.order_id
                or case.intake.draft.purchase_reference
                or "",
                "description": case.intake.draft.description or "",
                "requested_resolution": case.intake.draft.requested_resolution or "",
                "missing_fields": json.dumps(case.intake.completeness.missing_fields),
                "evidence_ids": json.dumps(files),
                "review_flags": json.dumps(case.intake.completeness.review_flags),
            }
            queue_key = f"{root}:queue:{case.revision}"

            async def queue() -> ConnectorResult:
                return await self._queue(case, values, queue_key)

            queued = await self.ledger.once(
                context=context,
                key=queue_key,
                digest=NormalizedParameters.from_value(values).digest,
                operation="sheets.update_row",
                effect=queue,
            )
            outcome["sheets"] = queued.status
            if queued.status != "SUCCEEDED" or queued.data.get("superseded"):
                return outcome
            notice_key = f"{root}:notice:{case.revision}"
            notice: dict[str, object] = {
                "recipient": self.configuration.notify,
                "subject": f"Caso {case.case_id}: {case.status}",
                "text": f"Caso {case.case_id}, revisión {case.revision}. Estado: {case.status}.\nLa resolución solicitada no es una decisión aprobada.\nRevise la cola configurada y la evidencia privada; no responda con aprobaciones automáticas.",
            }

            async def notify() -> ConnectorResult:
                return await self._call(
                    "gmail", "gmail.send_approval_notice", notice, notice_key
                )

            sent = await self.ledger.once(
                context=context,
                key=notice_key,
                digest=NormalizedParameters.from_value(notice).digest,
                operation="gmail.send_approval_notice",
                effect=notify,
            )
            outcome["gmail"] = sent.status
        return outcome

    async def _queue(
        self, case: ClaimCase, values: dict[str, object], key: str
    ) -> ConnectorResult:
        match: dict[str, object] | None = None
        start = 2
        # Bounded scan. Never append if pagination is incomplete or IDs duplicate.
        for _ in range(20):
            read = await self._call(
                "google_sheets", "sheets.read_rows", {"start_row": start, "limit": 500}
            )
            rows = read.data.get("rows")
            if read.status != "SUCCEEDED" or not isinstance(rows, list):
                return ConnectorResult(
                    operation="sheets.update_row",
                    status="FAILED",
                    error_code="claim_queue_read_unavailable",
                )
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("values"), dict):
                    return ConnectorResult(
                        operation="sheets.update_row",
                        status="FAILED",
                        error_code="claim_queue_invalid",
                    )
                if row["values"].get("case_id") == str(case.case_id):
                    if match is not None:
                        return ConnectorResult(
                            operation="sheets.update_row",
                            status="REJECTED",
                            error_code="claim_queue_duplicate",
                        )
                    match = row
            next_row = read.data.get("next_row")
            if next_row is None:
                break
            if type(next_row) is not int or next_row <= start:
                return ConnectorResult(
                    operation="sheets.update_row",
                    status="FAILED",
                    error_code="claim_queue_invalid",
                )
            start = next_row
        else:
            return ConnectorResult(
                operation="sheets.update_row",
                status="FAILED",
                error_code="claim_queue_scan_limit",
            )
        if match is None:
            result = await self._call(
                "google_sheets", "sheets.append_row", {"values": values}, key
            )
            return result.model_copy(update={"operation": "sheets.update_row"})
        existing = match["values"]
        assert isinstance(existing, dict)
        revision = existing.get("revision")
        if type(revision) is not int or revision < 1:
            return ConnectorResult(
                operation="sheets.update_row",
                status="REJECTED",
                error_code="claim_queue_revision_invalid",
            )
        if revision > case.revision:
            return ConnectorResult(
                operation="sheets.update_row",
                status="SUCCEEDED",
                data={"superseded": True},
            )
        if existing == values:
            return ConnectorResult(
                operation="sheets.update_row", status="SUCCEEDED", data={"reused": True}
            )
        if revision == case.revision:
            return ConnectorResult(
                operation="sheets.update_row",
                status="REJECTED",
                error_code="claim_queue_revision_conflict",
            )
        return await self._call(
            "google_sheets",
            "sheets.update_row",
            {
                "row_number": match.get("row_number"),
                "values": values,
                "expected": existing,
            },
            key,
        )
