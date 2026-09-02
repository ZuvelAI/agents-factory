from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from agents_factory.common.audit import AuditService
from agents_factory.common.errors import DomainError
from agents_factory.common.outbox import OutboxService
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.cases.claims_contracts import UnavailableClaimCases
from agents_factory.modules.capabilities.registry import V1_CAPABILITY_REGISTRY
from agents_factory.modules.capabilities.returns_claims.configuration import (
    ClaimsConfiguration,
)
from agents_factory.modules.capabilities.returns_claims.destination import (
    GoogleClaimDestination,
    GoogleClaimsDelivery,
    QUEUE_FIELDS,
)
from agents_factory.modules.capabilities.returns_claims.models import (
    ClaimsBinding,
    ISSUE_CLASSES,
)
from agents_factory.modules.capabilities.returns_claims.service import (
    ClaimsIntakeService,
    ClaimIntakeRejected,
)
from agents_factory.modules.capabilities.returns_claims.sources import (
    NativeClaimSources,
)
from agents_factory.modules.capabilities.returns_claims.tools import ClaimsToolSession
from agents_factory.modules.capabilities.returns_claims.workflow import (
    ClaimsActionConnector,
    ClaimsWorkflow,
    SUBMIT,
    STATUS,
)
from agents_factory.modules.identity.service import IdentityService
from agents_factory.modules.integrations.contracts import ConnectorRequest
from agents_factory.modules.integrations.google.drive import DriveResource
from agents_factory.modules.integrations.google.gmail import GmailResource
from agents_factory.modules.integrations.google.sheets import SheetsResource
from agents_factory.modules.knowledge.models import (
    KnowledgeDocumentDraft,
    KnowledgeProvenance,
)
from agents_factory.modules.knowledge.repository import KnowledgeRepository
from agents_factory.modules.knowledge.service import KnowledgeService
from agents_factory.modules.media.contracts import StoredMedia, MediaError
from agents_factory.modules.media.service import MediaService
from agents_factory.modules.media.storage import (
    LocalPrivateMediaStore,
    MediaAccessSigner,
)
from agents_factory.modules.runtime.contracts import ToolInvocationContext
from agents_factory.modules.secrets.redaction import ResolvedSecret
from apps.backend.tests.claims_support import (
    ClaimCasesFixture,
    DeliveryLedgerFixture,
    GoogleClaimsFixture,
)
from apps.backend.tests.integration.capabilities.test_orders import order_world  # noqa: F401


@dataclass
class ClaimsWorld:
    base: object
    workflow: ClaimsWorkflow
    configuration: ClaimsConfiguration
    google: GoogleClaimsFixture
    ledger: DeliveryLedgerFixture
    media: MediaService
    evidence_id: UUID

    def actions(self, session):
        return ActionService(
            context=self.base.context,
            repository=ActionRepository(session, self.base.context),
            identity_guard=IdentityService(context=self.base.context, store=Mock()),
            connector=ClaimsActionConnector(self.workflow),
            approval_verifier=Mock(),
            audit=AuditService(session),
            outbox=OutboxService(session),
        )

    async def request(
        self,
        arguments,
        *,
        operation=SUBMIT,
        customer="customer",
        action_id=None,
        message_id=None,
    ):
        async with self.base.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            return await self.workflow.request_action(
                actions=self.actions(session),
                action_id=action_id or uuid4(),
                message_id=message_id or uuid4(),
                conversation_id=self.base.conversation,
                customer_ref=customer,
                binding_id=self.configuration.binding.binding_id,
                operation=operation,
                arguments=arguments,
            )

    async def confirm(self, action, *, digest=None):
        async with self.base.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            return await self.actions(session).confirm(
                action_id=action.id,
                parameter_digest=digest or action.parameter_digest,
                customer_ref="customer",
            )

    async def execute(self, action, *, rollback=False):
        async with self.base.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            result = await self.actions(session).execute(action_id=action.id)
            if rollback:
                raise RuntimeError("fixture outer transaction interrupted")
            return result


@pytest.fixture
async def claims_world(order_world, tmp_path):  # noqa: F811
    base = order_world
    tenant = base.context.tenant_id
    async with base.sessions.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        knowledge = KnowledgeService(KnowledgeRepository(session, base.context))
        source = await knowledge.create_source(
            name="Returns policy", source_type="MANUAL", authority="AUTHORITATIVE"
        )
        source_version = await knowledge.append_source_version(
            source_id=source.id,
            version_number=1,
            content_digest="a" * 64,
            verified_at=datetime.now(UTC),
            locator={},
        )
        document = await knowledge.add_document(
            KnowledgeDocumentDraft(
                category="POLICY",
                title="Claims",
                text="Recepción para revisión humana; conservar evidencia disponible.",
                locator={},
                provenance=KnowledgeProvenance(
                    source_id=source.id,
                    source_version_id=source_version.id,
                    authority="AUTHORITATIVE",
                    verified_at=source_version.verified_at,
                    approved_by_admin_id=base.context.actor_id,
                    content_digest="b" * 64,
                ),
            )
        )
        version = await knowledge.create_version(name="Claims fixture")
        await knowledge.add_members(version_id=version.id, document_ids=(document.id,))
        # Fixture-only TEST membership. This is NOT production Quality Gate evidence.
        await session.execute(
            text(
                "UPDATE public.knowledge_versions SET state='TEST', digest=:digest WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": tenant, "id": version.id, "digest": "c" * 64},
        )
    binding = ClaimsBinding(
        tenant_id=tenant,
        binding_id=uuid4(),
        knowledge_version_id=version.id,
        knowledge_digest="c" * 64,
    )
    fields = sorted(QUEUE_FIELDS)
    destination = GoogleClaimDestination(
        tenant_id=tenant,
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
        drive=DriveResource(
            evidence_folder_id="evidence-folder", max_bytes=20 * 1024 * 1024
        ),
        gmail=GmailResource(
            sender="operations@example.test",
            approval_recipients=frozenset({"review@example.test"}),
        ),
        notify="review@example.test",
    )
    configuration = ClaimsConfiguration(
        binding=binding,
        orders_binding_id=next(iter(base.bindings)),
        policy_document_id=document.id,
        policy_document_digest="b" * 64,
        policy_requirements={issue: () for issue in ISSUE_CLASSES},
        environment="TEST",
        destination_digest=destination.digest,
    )
    media = MediaService(
        sessions=base.sessions,
        provider=Mock(),
        storage=LocalPrivateMediaStore(tmp_path / "originals"),
        signer=MediaAccessSigner(
            ResolvedSecret(b"fixture-media-signing-material-12345")
        ),
    )
    evidence_id = uuid4()
    media_message_id = uuid4()
    original = b"\x00\x00\x00\x18ftypisom" + b"fixture-video-original"
    storage_key, digest = await media.storage.put(
        tenant_id=tenant, media_id=evidence_id, content=original
    )
    stored_at = datetime.now(UTC)
    async with base.sessions.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.messages(id,tenant_id,conversation_id,direction,sender_type,message_type,content,provider_timestamp,arrival_sequence) VALUES (:id,:tenant,:conversation,'inbound','customer','video','{}',now(),1)"
            ),
            {
                "id": media_message_id,
                "tenant": tenant,
                "conversation": base.conversation,
            },
        )
        account = await session.scalar(
            text("SELECT whatsapp_account_id FROM public.conversations WHERE id=:id"),
            {"id": base.conversation},
        )
    await media._save(
        base.context,
        StoredMedia(
            id=evidence_id,
            tenant_id=tenant,
            whatsapp_account_id=account,
            provider_media_id=str(uuid4().int),
            customer_ref="customer",
            first_message_id=media_message_id,
            kind="video",
            content_digest=digest,
            storage_key=storage_key,
            media_type="video/mp4",
            byte_size=len(original),
            stored_at=stored_at,
            status="HUMAN_REVIEW",
            scan_status="CLEAN",
            created_at=stored_at,
            expires_at=stored_at + timedelta(days=1),
        ),
    )
    google, ledger, cases = (
        GoogleClaimsFixture(destination),
        DeliveryLedgerFixture(),
        ClaimCasesFixture(),
    )
    workflow = ClaimsWorkflow(
        context=base.context,
        sessions=base.sessions,
        configurations=lambda identifier: configuration
        if identifier == binding.binding_id
        else None,
        sources=NativeClaimSources(
            context=base.context,
            sessions=base.sessions,
            orders=base.orders,
            allow_test=True,
        ),
        intake=ClaimsIntakeService(evidence=media),
        cases=cases,
        destination=GoogleClaimsDelivery(destination, google.connectors, ledger, media),
    )
    return ClaimsWorld(
        base, workflow, configuration, google, ledger, media, evidence_id
    )


async def test_confirmed_partial_case_destination_replay_and_verified_status(
    claims_world,
):
    world = claims_world
    action_id, message_id = uuid4(), uuid4()
    arguments = {
        "issue_type": "damaged_product",
        "order_id": "42",
        "description": "Llegó roto",
    }
    action = await world.request(arguments, action_id=action_id, message_id=message_id)
    assert action.state == "AWAITING_CONFIRMATION"
    assert not world.workflow.cases.records and not world.google.writes
    with pytest.raises(DomainError):
        await world.execute(action)
    assert (
        await world.request(arguments, action_id=action_id, message_id=message_id)
    ).id == action.id
    await world.confirm(action)
    first = await world.execute(action)
    assert first.state == "SUCCEEDED"
    assert first.result["data"]["case_status"] == "AWAITING_INFORMATION"
    case_id = UUID(first.result["data"]["case_id"])
    update = await world.request(
        {
            "case_id": str(case_id),
            "item_ids": ["1"],
            "evidence_ids": [str(world.evidence_id)],
            "requested_resolution": "Solicito reembolso",
        }
    )
    await world.confirm(update)
    outcome = await world.execute(update)
    assert outcome.result["data"]["case_status"] == "READY_FOR_REVIEW"
    assert outcome.result["data"]["business_decision"] == "NOT_MADE"
    assert world.google.writes == ["append", "gmail", "drive", "update", "gmail"]
    snapshot = world.workflow.cases.records[case_id]
    repeated = await world.request(
        {"case_id": str(case_id), **snapshot.intake.draft.model_dump(mode="json")}
    )
    await world.confirm(repeated)
    await world.execute(repeated)
    assert len(world.workflow.cases.records) == 1 and len(world.google.rows) == 2
    assert world.workflow.cases.records[case_id].revision == 2
    assert world.google.writes == ["append", "gmail", "drive", "update", "gmail"]
    await world.execute(update)
    assert world.google.writes.count("drive") == 1
    exported = await world.media.export_evidence(
        context=world.base.context,
        customer_ref="customer",
        evidence_id=world.evidence_id,
    )
    assert exported.media_type == "video/mp4" and b"fixture-video" in exported.content
    for context, customer in (
        (world.base.context, "foreign"),
        (replace(world.base.context, tenant_id=uuid4()), "customer"),
    ):
        with pytest.raises(MediaError):
            await world.media.export_evidence(
                context=context, customer_ref=customer, evidence_id=world.evidence_id
            )
    with pytest.raises(ClaimIntakeRejected):
        await world.request(
            {"case_id": str(case_id)}, operation=STATUS, customer="other"
        )
    world.workflow.cases.records[case_id] = snapshot.model_copy(
        update={
            "status": "RESOLVED",
            "customer_result": "El equipo registró una reposición.",
            "result_recorded_by": uuid4(),
        }
    )
    status = await world.request({"case_id": str(case_id)}, operation=STATUS)
    verified = await world.execute(status)
    assert verified.result["data"]["result_source"] == "backoffice"
    assert verified.result["data"]["case_status"] == "RESOLVED"
    assert (
        V1_CAPABILITY_REGISTRY.get("returns_claims", "1.0.0").stable_name
        == "returns_claims"
    )


async def test_claim_conflicts_outage_crash_and_runtime_guards(claims_world):
    world = claims_world
    args = {
        "issue_type": "return_request",
        "order_id": "42",
        "description": "Solicito revisión",
        "requested_resolution": "Devolución",
    }
    action = await world.request(args)
    connector = ClaimsActionConnector(world.workflow)
    request = ConnectorRequest(
        tenant_id=world.base.context.tenant_id,
        binding_id=world.configuration.binding.binding_id,
        operation=SUBMIT,
        arguments=action.parameters,
        idempotency_key=str(action.id),
    )
    assert (await connector.execute(request)).status == "REJECTED"
    assert not (await connector.revalidate(action)).valid
    await world.confirm(action)
    world.google.fail_gmail = True
    with pytest.raises(RuntimeError, match="outer transaction interrupted"):
        await world.execute(action, rollback=True)
    assert len(world.workflow.cases.records) == 1
    assert world.google.writes == ["append", "gmail"]
    recovered = await world.execute(action)
    assert recovered.state == "SUCCEEDED"
    assert recovered.result["data"]["delivery"]["gmail"] == "UNCERTAIN"
    assert world.google.writes == ["append", "gmail"]
    case_id = recovered.result["data"]["case_id"]
    one = await world.request(
        {"case_id": case_id, "description": "Nueva información A"}
    )
    two = await world.request(
        {"case_id": case_id, "description": "Nueva información B"}
    )
    await world.confirm(one)
    await world.confirm(two)
    assert (await world.execute(one)).state == "SUCCEEDED"
    writes = list(world.google.writes)
    conflict = await world.execute(two)
    assert conflict.state == "FAILED"
    assert conflict.result["connector_status"] == "REJECTED"
    assert conflict.result["error_code"] == "claim_changed_requires_confirmation"
    assert world.google.writes == writes
    stale = await world.request({"case_id": case_id, "description": "Cambio pendiente"})
    await world.confirm(stale)
    changed = world.configuration.model_copy(update={"destination_digest": "f" * 64})
    world.workflow.configurations = lambda _: changed
    assert (await world.execute(stale)).state == "FAILED"
    world.workflow.configurations = lambda _: world.configuration
    invocation = ToolInvocationContext(
        tenant_id=world.base.context.tenant_id,
        conversation_id=world.base.conversation,
        inbound_message_id=uuid4(),
        correlation_id=uuid4(),
    )
    async with world.base.sessions.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        tool_session = ClaimsToolSession(
            invocation,
            world.workflow,
            world.actions(session),
            world.configuration.binding.binding_id,
            "customer",
        )
        tools = {tool.name: tool for tool in tool_session.tools()}
        assert set(tools) == {SUBMIT, STATUS}
        assert (
            await tools[STATUS].handler(
                replace(invocation, tenant_id=uuid4()), {"case_id": case_id}
            )
        )["state"] == "REJECTED"
        assert (await tools[SUBMIT].handler(invocation, {**args, "approved": True}))[
            "state"
        ] == "UNAVAILABLE"
        world.workflow.destination = None
        assert {tool.name for tool in tool_session.tools()} == {STATUS}
        world.workflow.cases = UnavailableClaimCases()
        assert not tool_session.tools()


async def test_native_claim_policy_binding_and_source_revocation(claims_world):
    world = claims_world
    sources, configuration = world.workflow.sources, world.configuration
    assert (
        await sources.policy(configuration)
    ).document_id == configuration.policy_document_id
    assert (
        await sources.policy(
            configuration.model_copy(update={"policy_document_digest": "f" * 64})
        )
        is None
    )
    assert (
        await sources.policy(
            configuration.model_copy(
                update={
                    "binding": configuration.binding.model_copy(
                        update={"knowledge_digest": "f" * 64}
                    )
                }
            )
        )
        is None
    )
    with pytest.raises(ClaimIntakeRejected):
        await replace(sources, allow_test=False).policy(configuration)
    with pytest.raises(ClaimIntakeRejected):
        await sources.policy(
            configuration.model_copy(
                update={
                    "binding": configuration.binding.model_copy(
                        update={"tenant_id": uuid4()}
                    )
                }
            )
        )
    with pytest.raises(ClaimIntakeRejected):
        await world.request(
            {
                "issue_type": "return_request",
                "order_id": "42",
                "description": "Reporte",
                "requested_resolution": "Revisión",
            },
            customer="other",
        )
    action = await world.request(
        {
            "issue_type": "damaged_product",
            "order_id": "42",
            "description": "Daño",
            "item_ids": ["1"],
            "evidence_ids": [str(world.evidence_id)],
            "requested_resolution": "Revisión",
        }
    )
    await world.confirm(action)
    await world.media.delete(context=world.base.context, evidence_id=world.evidence_id)
    assert (await world.execute(action)).state == "FAILED"
    assert not world.workflow.cases.records and not world.google.writes
    with pytest.raises(MediaError):
        await world.media.export_evidence(
            context=world.base.context,
            customer_ref="customer",
            evidence_id=world.evidence_id,
        )
