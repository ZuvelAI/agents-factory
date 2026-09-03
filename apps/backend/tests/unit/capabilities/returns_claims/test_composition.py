from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agents_factory.common.context import TenantContext
from agents_factory.modules.cases.claims_contracts import ClaimCase
from agents_factory.modules.capabilities.registry import V1_CAPABILITY_REGISTRY
from agents_factory.modules.capabilities.service import (
    CapabilityService,
    AgentSpecManifestError,
)
from agents_factory.modules.capabilities.returns_claims.destination import (
    GoogleClaimDestination,
    GoogleClaimsDelivery,
    QUEUE_FIELDS,
)
from agents_factory.modules.capabilities.returns_claims.models import (
    ClaimDraft,
    ClaimsBinding,
    ClaimOrderReference,
)
from agents_factory.modules.capabilities.returns_claims.service import (
    ClaimsIntakeService,
)
from agents_factory.modules.capabilities.returns_claims.tools import customer_message
from agents_factory.modules.capabilities.returns_claims.workflow import SUBMIT, STATUS
from agents_factory.modules.identity.models import IdentityAssessment
from agents_factory.modules.integrations.contracts import ConnectorResult
from agents_factory.modules.integrations.google.drive import DriveResource
from agents_factory.modules.integrations.google.gmail import GmailResource
from agents_factory.modules.integrations.google.sheets import SheetsResource
from agents_factory.modules.integrations.registry import V1_CONNECTOR_CATALOG
from apps.backend.tests.claims_support import GoogleClaimsFixture, DeliveryLedgerFixture


async def test_multibinding_manifest_and_queue_reconciliation_guards():
    service = CapabilityService(
        capabilities=V1_CAPABILITY_REGISTRY, connectors=V1_CONNECTOR_CATALOG
    )
    bindings = [
        SimpleNamespace(
            connector="woocommerce",
            connector_version="1.0.0",
            operations=("orders.get_status",),
        ),
        SimpleNamespace(
            connector="google_drive",
            connector_version="1.0.0",
            operations=("drive.store_evidence",),
        ),
        SimpleNamespace(
            connector="google_sheets",
            connector_version="1.0.0",
            operations=("sheets.read_rows", "sheets.append_row", "sheets.update_row"),
        ),
        SimpleNamespace(
            connector="gmail",
            connector_version="1.0.0",
            operations=("gmail.send_approval_notice",),
        ),
    ]
    spec = SimpleNamespace(
        configuration=SimpleNamespace(
            capabilities=(SimpleNamespace(name="returns_claims", version="1.0.0"),),
            connector_bindings=bindings,
            permitted_tools=(SUBMIT, STATUS),
            permitted_actions=(),
            action_policies=(),
        )
    )
    service.validate_agent_spec(spec)
    spec.configuration.connector_bindings = bindings[:-1]
    with pytest.raises(AgentSpecManifestError, match="not supported"):
        service.validate_agent_spec(spec)
    spec.configuration.permitted_tools = (STATUS,)
    spec.configuration.connector_bindings = ()
    service.validate_agent_spec(spec)  # Runtime still requires an available Cases port.
    assert "has not been promised" in customer_message(
        state="SUCCEEDED", operation=SUBMIT, language="en"
    )
    assert "No pude confirmar" in customer_message(
        state="UNCERTAIN", operation=SUBMIT, language="es"
    )

    context = TenantContext(uuid4(), uuid4(), "system", uuid4())
    binding = ClaimsBinding(
        tenant_id=context.tenant_id,
        binding_id=uuid4(),
        knowledge_version_id=uuid4(),
        knowledge_digest="a" * 64,
    )
    intake = await ClaimsIntakeService().prepare(
        context=context,
        binding=binding,
        customer_ref="customer",
        assessment=IdentityAssessment(
            tenant_id=context.tenant_id,
            customer_ref="customer",
            achieved_level=1,
            evidence_ids=(),
            assessed_at=datetime.now(UTC),
        ),
        message_id=uuid4(),
        draft=ClaimDraft(
            issue_type="return_request",
            order_id="42",
            description="Revisión",
            requested_resolution="Devolución",
        ),
        order_reference=ClaimOrderReference(
            tenant_id=context.tenant_id,
            binding_id=binding.binding_id,
            customer_ref="customer",
            resource_id="order:42",
            order_id="42",
            order_verified=True,
        ),
    )
    case = ClaimCase(
        case_id=uuid4(), intake=intake, revision=1, status=intake.completeness.state
    )
    fields = sorted(QUEUE_FIELDS)
    destination = GoogleClaimDestination(
        tenant_id=context.tenant_id,
        binding_id=binding.binding_id,
        sheets_connection_id=uuid4(),
        drive_connection_id=uuid4(),
        gmail_connection_id=uuid4(),
        sheets=SheetsResource(
            spreadsheet_id="claims-sheet",
            tab="Cases",
            headers=tuple(fields),
            fields={field: field for field in fields},
        ),
        drive=DriveResource(evidence_folder_id="evidence-folder"),
        gmail=GmailResource(
            sender="operations@example.test",
            approval_recipients=frozenset({"review@example.test"}),
        ),
        notify="review@example.test",
    )

    class NoEvidence:
        async def export_evidence(self, **kwargs):
            raise AssertionError("fixture has no evidence")

    for revision, duplicates, expected in (
        (2, False, "SUCCEEDED"),
        (1, True, "REJECTED"),
    ):
        google = GoogleClaimsFixture(destination)
        row = {field: "" for field in fields}
        row.update(case_id=str(case.case_id), revision=revision, status="IN_PROGRESS")
        google.rows.append([row[field] for field in fields])
        if duplicates:
            google.rows.append(list(google.rows[1]))
        delivery = GoogleClaimsDelivery(
            destination, google.connectors, DeliveryLedgerFixture(), NoEvidence()
        )
        result = await delivery.deliver(context=context, case=case)
        assert result["sheets"] == expected and "gmail" not in result
        assert not google.writes

    class UncertainLedger(DeliveryLedgerFixture):
        async def once(self, *, context, key, digest, operation, effect):
            return ConnectorResult(operation=operation, status="UNCERTAIN")

    google = GoogleClaimsFixture(destination)
    delivery = GoogleClaimsDelivery(
        destination, google.connectors, UncertainLedger(), NoEvidence()
    )
    assert (await delivery.deliver(context=context, case=case))["sheets"] == "UNCERTAIN"
    assert not google.writes
