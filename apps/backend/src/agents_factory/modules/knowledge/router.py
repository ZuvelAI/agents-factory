from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.knowledge.models import (
    AuthorityResolution,
    KnowledgeDocument,
    KnowledgeDocumentDraft,
    KnowledgeIngestion,
    KnowledgeProvenance,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeVersion,
    StructuredFact,
)
from agents_factory.modules.knowledge.repository import KnowledgeRepository
from agents_factory.modules.knowledge.schemas import (
    AddKnowledgeDocumentRequest,
    AddKnowledgeMembersRequest,
    AddStructuredFactRequest,
    AppendSourceVersionRequest,
    CreateKnowledgeSourceRequest,
    CreateKnowledgeVersionRequest,
    EmbeddingJobResponse,
    KnowledgeEvalEvidenceRequest,
    KnowledgeUploadResponse,
    ReviewKnowledgeProposalRequest,
)
from agents_factory.modules.knowledge.proposals import (
    KnowledgeProposal,
    KnowledgeProposalService,
    ProposalReview,
)
from agents_factory.modules.knowledge.publishing import KnowledgeEvalEvidence
from agents_factory.modules.knowledge.service import KnowledgeService
from agents_factory.modules.knowledge.ingestion.contracts import MAX_SOURCE_BYTES
from agents_factory.modules.knowledge.ingestion.storage import LocalPrivateSourceStore
from agents_factory.modules.knowledge.workspace import (
    KnowledgeWorkspace,
    KnowledgeWorkspaceService,
)
from agents_factory.modules.evals.quality_gate import PersistedKnowledgeQualityGate


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/knowledge",
    tags=["platform-admin-knowledge"],
)


@router.get("/workspace", response_model=KnowledgeWorkspace)
async def workspace(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeWorkspace:
    return await KnowledgeWorkspaceService(
        session, _context(request, principal, tenant_id)
    ).read()


@router.post("/sources", response_model=KnowledgeSource, status_code=201)
async def create_source(
    tenant_id: UUID,
    payload: CreateKnowledgeSourceRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeSource:
    return await _service(request, principal, tenant_id, session).create_source(
        name=payload.name,
        source_type=payload.source_type,
        authority=payload.authority,
        configuration=payload.configuration,
    )


@router.post(
    "/sources/{source_id}/ingestions",
    response_model=KnowledgeIngestion,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_source_ingestion(
    tenant_id: UUID,
    source_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeIngestion:
    return await _service(request, principal, tenant_id, session).request_ingestion(
        source_id
    )


@router.put(
    "/sources/{source_id}/uploads/{upload_key}",
    response_model=KnowledgeUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source_file(
    tenant_id: UUID,
    source_id: UUID,
    upload_key: str,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeUploadResponse:
    service = _service(request, principal, tenant_id, session)
    source = await service.get_source(source_id)
    media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    allowed = {
        "PDF": {"application/pdf"},
        "DOCX": {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        },
        "SPREADSHEET": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        },
    }
    expected_media = allowed.get(source.source_type)
    if (
        expected_media is None
        or source.configuration.get("upload_key") != upload_key
        or media_type not in expected_media
    ):
        raise _upload_error("knowledge_upload_type_invalid", status=422)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_SOURCE_BYTES:
            raise _upload_error("knowledge_upload_too_large", status=413)
    if not content:
        raise _upload_error("knowledge_upload_empty", status=422)
    store = getattr(request.app.state, "knowledge_source_store", None)
    if not isinstance(store, LocalPrivateSourceStore):
        raise _upload_error("knowledge_upload_unavailable", status=503)
    await store.put_upload(
        tenant_id=tenant_id,
        source_id=source_id,
        upload_key=upload_key,
        content=bytes(content),
        media_type=media_type,
    )
    await AuditService(session).record(
        context=_context(request, principal, tenant_id),
        event_type="knowledge.source.uploaded",
        entity_type="knowledge_source",
        entity_id=source_id,
        payload={"source_type": source.source_type, "size_bytes": len(content)},
    )
    return KnowledgeUploadResponse(upload_key=upload_key, size_bytes=len(content))


@router.post(
    "/sources/{source_id}/versions",
    response_model=KnowledgeSourceVersion,
    status_code=status.HTTP_201_CREATED,
)
async def append_source_version(
    tenant_id: UUID,
    source_id: UUID,
    payload: AppendSourceVersionRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeSourceVersion:
    return await _service(request, principal, tenant_id, session).append_source_version(
        source_id=source_id,
        version_number=payload.version_number,
        content_digest=payload.content_digest,
        verified_at=payload.verified_at,
        locator=payload.locator,
    )


@router.post("/facts", response_model=StructuredFact, status_code=201)
async def add_structured_fact(
    tenant_id: UUID,
    payload: AddStructuredFactRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> StructuredFact:
    return await _service(request, principal, tenant_id, session).add_structured_fact(
        payload.fact
    )


@router.post("/documents", response_model=KnowledgeDocument, status_code=201)
async def add_document(
    tenant_id: UUID,
    payload: AddKnowledgeDocumentRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeDocument:
    service = _service(request, principal, tenant_id, session)
    source = await service.get_source_version(
        source_id=payload.source_id,
        source_version_id=payload.source_version_id,
    )
    return await service.add_document(
        KnowledgeDocumentDraft(
            category=payload.category,
            title=payload.title,
            text=payload.text,
            locator=payload.locator,
            provenance=KnowledgeProvenance(
                source_id=source.source_id,
                source_version_id=source.id,
                authority=source.authority,
                verified_at=source.verified_at,
                approved_by_admin_id=source.approved_by_admin_id,
                content_digest=payload.content_digest,
            ),
        )
    )


@router.post("/versions", response_model=KnowledgeVersion, status_code=201)
async def create_version(
    tenant_id: UUID,
    payload: CreateKnowledgeVersionRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeVersion:
    return await _service(request, principal, tenant_id, session).create_version(
        name=payload.name,
        based_on_version_id=payload.based_on_version_id,
    )


@router.post("/versions/{version_id}/members", response_model=KnowledgeVersion)
async def add_version_members(
    tenant_id: UUID,
    version_id: UUID,
    payload: AddKnowledgeMembersRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeVersion:
    return await _service(request, principal, tenant_id, session).add_members(
        version_id=version_id,
        structured_fact_ids=payload.structured_fact_ids,
        document_ids=payload.document_ids,
    )


@router.post("/versions/{version_id}/test", response_model=KnowledgeVersion)
async def promote_version_to_test(
    tenant_id: UUID,
    version_id: UUID,
    payload: KnowledgeEvalEvidenceRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeVersion:
    return await _service(request, principal, tenant_id, session).promote_to_test(
        version_id,
        evidence=KnowledgeEvalEvidence(
            id=payload.id,
            knowledge_digest=payload.knowledge_digest,
            suite_digest=payload.suite_digest,
            runner_version=payload.runner_version,
            passed=payload.passed,
            passed_cases=payload.passed_cases,
            failed_cases=payload.failed_cases,
        ),
    )


@router.post("/versions/{version_id}/test-v0", response_model=KnowledgeVersion)
async def promote_version_to_test_v0(
    tenant_id: UUID,
    version_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeVersion:
    return await _service(request, principal, tenant_id, session).promote_to_test_v0(
        version_id
    )


@router.post("/versions/{version_id}/production", response_model=KnowledgeVersion)
async def publish_version_to_production(
    tenant_id: UUID,
    version_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeVersion:
    return await _service(request, principal, tenant_id, session).publish_production(
        version_id
    )


@router.post("/proposals/{proposal_id}/review", response_model=KnowledgeProposal)
async def review_proposal(
    tenant_id: UUID,
    proposal_id: UUID,
    payload: ReviewKnowledgeProposalRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> KnowledgeProposal:
    context = TenantContext(
        tenant_id=tenant_id,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
    )
    return await KnowledgeProposalService(session=session, context=context).review(
        proposal_id=proposal_id,
        review=ProposalReview(
            revision=payload.revision,
            decision=payload.decision,
            edited_payload=payload.edited_payload,
        ),
    )


@router.post(
    "/versions/{version_id}/embeddings",
    response_model=EmbeddingJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_version_embeddings(
    tenant_id: UUID,
    version_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> EmbeddingJobResponse:
    job_id = await _service(request, principal, tenant_id, session).request_embeddings(
        version_id
    )
    return EmbeddingJobResponse(job_id=job_id, knowledge_version_id=version_id)


@router.get(
    "/versions/{version_id}/facts/{fact_key}",
    response_model=AuthorityResolution,
)
async def resolve_structured_fact(
    tenant_id: UUID,
    version_id: UUID,
    fact_key: str,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AuthorityResolution:
    return await _service(request, principal, tenant_id, session).resolve_fact(
        version_id=version_id,
        key=fact_key,
    )


def _service(
    request: Request,
    principal: AdminPrincipal,
    tenant_id: UUID,
    session: TransactionSession,
) -> KnowledgeService:
    context = _context(request, principal, tenant_id)
    return KnowledgeService(
        KnowledgeRepository(session, context),
        production_gate=PersistedKnowledgeQualityGate(session, tenant_id),
    )


def _context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
    )


def _upload_error(code: str, *, status: int) -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/knowledge-upload",
        title="Knowledge Upload Rejected",
        status=status,
        detail="The Knowledge source file could not be accepted.",
        code=code,
    )
