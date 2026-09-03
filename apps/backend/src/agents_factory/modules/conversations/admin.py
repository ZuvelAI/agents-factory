from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TEXT
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.database import set_tenant_context
from agents_factory.dependencies import TransactionSession


ReviewCategory = Literal[
    "AI_RESOLVED",
    "HUMAN_HANDOFF",
    "TOOL_FAILURE",
    "POLICY_VIOLATION",
    "COMPLAINT",
    "HIGH_COST",
    "FLAGGED",
]
ReviewLabel = Literal[
    "CORRECT",
    "INCORRECT",
    "UNSAFE",
    "KNOWLEDGE_PROBLEM",
    "INTEGRATION_PROBLEM",
    "MODEL_REASONING_PROBLEM",
]
TestMode = Literal["SANDBOX_SIMULATED", "REAL_TEST_ENVIRONMENT"]


class AdminConversationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ConversationReview(AdminConversationModel):
    id: UUID
    conversation_id: UUID
    revision: int = Field(ge=1)
    categories: tuple[ReviewCategory, ...]
    labels: tuple[ReviewLabel, ...]
    note: str | None
    reviewed_by_admin_id: UUID
    updated_at: datetime


class ConversationOverview(AdminConversationModel):
    id: UUID
    customer_reference: str
    control_state: str
    message_count: int = Field(ge=0)
    opened_at: datetime
    latest_message_at: datetime | None
    review: ConversationReview | None


class EvalCaseDraft(AdminConversationModel):
    id: UUID
    conversation_id: UUID
    case_id: str
    schema_version: Literal[1] = 1
    payload: dict[str, object]
    status: Literal["DRAFT"] = "DRAFT"
    created_at: datetime


class ConversationWorkspace(AdminConversationModel):
    conversations: tuple[ConversationOverview, ...]
    eval_drafts: tuple[EvalCaseDraft, ...]
    categories: tuple[ReviewCategory, ...] = (
        "AI_RESOLVED",
        "HUMAN_HANDOFF",
        "TOOL_FAILURE",
        "POLICY_VIOLATION",
        "COMPLAINT",
        "HIGH_COST",
        "FLAGGED",
    )
    labels: tuple[ReviewLabel, ...] = (
        "CORRECT",
        "INCORRECT",
        "UNSAFE",
        "KNOWLEDGE_PROBLEM",
        "INTEGRATION_PROBLEM",
        "MODEL_REASONING_PROBLEM",
    )


class TimelineMessage(AdminConversationModel):
    id: UUID
    direction: str
    sender_type: str
    message_type: str
    text: str
    occurred_at: datetime
    agent_spec_id: UUID | None
    agent_spec_version: str | None
    runtime_metadata: dict[str, object]


class ConversationDetail(AdminConversationModel):
    conversation: ConversationOverview
    messages: tuple[TimelineMessage, ...]


class SaveReviewRequest(AdminConversationModel):
    expected_revision: int = Field(ge=0)
    categories: tuple[ReviewCategory, ...]
    labels: tuple[ReviewLabel, ...]
    note: str | None = Field(default=None, max_length=2_000)


class ExportEvalDraftRequest(AdminConversationModel):
    reason: str = Field(min_length=1, max_length=500)


class TestReadiness(AdminConversationModel):
    sandbox_available: Literal[True] = True
    real_test_available: bool
    real_test_reason: str | None


class TestRunRequest(AdminConversationModel):
    mode: TestMode
    message: str = Field(min_length=1, max_length=4_000)


class TestRunInspector(AdminConversationModel):
    id: UUID
    tenant_id: UUID
    mode: TestMode
    simulated: bool
    response: str
    agent_spec: dict[str, object]
    knowledge: dict[str, object] | None
    intent: str
    capability: str
    identity: dict[str, object]
    tools: tuple[dict[str, object], ...]
    sources: tuple[dict[str, object], ...]
    action: dict[str, object]
    approval: dict[str, object]
    usage: dict[str, object]
    latency_ms: int = Field(ge=0)
    trace_id: UUID
    created_at: datetime


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}", tags=["platform-admin-conversations"]
)


@router.get("/conversations/review-workspace", response_model=ConversationWorkspace)
async def review_workspace(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
    category: ReviewCategory | None = None,
) -> ConversationWorkspace:
    return await ConversationAdminService(
        session, _context(request, principal, tenant_id)
    ).workspace(category)


@router.get(
    "/conversations/{conversation_id}/review-detail",
    response_model=ConversationDetail,
)
async def review_detail(
    tenant_id: UUID,
    conversation_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> ConversationDetail:
    return await ConversationAdminService(
        session, _context(request, principal, tenant_id)
    ).detail(conversation_id)


@router.put(
    "/conversations/{conversation_id}/review", response_model=ConversationReview
)
async def save_review(
    tenant_id: UUID,
    conversation_id: UUID,
    payload: SaveReviewRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> ConversationReview:
    return await ConversationAdminService(
        session, _context(request, principal, tenant_id)
    ).save_review(conversation_id, payload)


@router.post(
    "/conversations/{conversation_id}/eval-drafts",
    response_model=EvalCaseDraft,
    status_code=201,
)
async def export_eval_draft(
    tenant_id: UUID,
    conversation_id: UUID,
    payload: ExportEvalDraftRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> EvalCaseDraft:
    return await ConversationAdminService(
        session, _context(request, principal, tenant_id)
    ).export_eval_draft(conversation_id, payload.reason)


@router.get("/test-console/readiness", response_model=TestReadiness)
async def test_readiness(
    tenant_id: UUID,
    _principal: PlatformAdmin,
) -> TestReadiness:
    _ = tenant_id
    return TestReadiness(
        real_test_available=False,
        real_test_reason=(
            "A dedicated test tenant and provider accounts have not been configured."
        ),
    )


@router.post("/test-console/runs", response_model=TestRunInspector)
async def run_test(
    tenant_id: UUID,
    payload: TestRunRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> TestRunInspector:
    return await ConversationAdminService(
        session, _context(request, principal, tenant_id)
    ).run(payload)


class ConversationAdminService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def workspace(self, category: ReviewCategory | None) -> ConversationWorkspace:
        await set_tenant_context(self._session, self._context.tenant_id)
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT conversation.id,conversation.customer_wa_id,"
                        "conversation.control_state,conversation.opened_at,"
                        "count(message.id) AS message_count,"
                        "max(message.provider_timestamp) AS latest_message_at,"
                        "review.id AS review_id,review.revision,review.categories,"
                        "review.labels,review.note,review.reviewed_by_admin_id,"
                        "review.updated_at FROM public.conversations AS conversation "
                        "LEFT JOIN public.messages AS message "
                        "ON message.tenant_id=conversation.tenant_id "
                        "AND message.conversation_id=conversation.id LEFT JOIN "
                        "public.conversation_reviews AS review "
                        "ON review.tenant_id=conversation.tenant_id "
                        "AND review.conversation_id=conversation.id "
                        "WHERE conversation.tenant_id=:tenant "
                        "AND (:category IS NULL OR :category=ANY(review.categories)) "
                        "GROUP BY conversation.id,review.id "
                        "ORDER BY max(message.provider_timestamp) DESC NULLS LAST,"
                        "conversation.opened_at DESC LIMIT 200"
                    ),
                    {"tenant": self._context.tenant_id, "category": category},
                )
            )
            .mappings()
            .all()
        )
        drafts = await self._eval_drafts()
        return ConversationWorkspace(
            conversations=tuple(_overview(row) for row in rows),
            eval_drafts=drafts,
        )

    async def detail(self, conversation_id: UUID) -> ConversationDetail:
        workspace = await self.workspace(None)
        overview = next(
            (item for item in workspace.conversations if item.id == conversation_id),
            None,
        )
        if overview is None:
            raise _conversation_error("conversation_not_found", status=404)
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id,direction,sender_type,message_type,content,"
                        "provider_timestamp,agent_spec_id,agent_spec_version,"
                        "runtime_metadata FROM public.messages WHERE tenant_id=:tenant "
                        "AND conversation_id=:conversation "
                        "ORDER BY provider_timestamp,arrival_sequence LIMIT 500"
                    ),
                    {
                        "tenant": self._context.tenant_id,
                        "conversation": conversation_id,
                    },
                )
            )
            .mappings()
            .all()
        )
        return ConversationDetail(
            conversation=overview,
            messages=tuple(_timeline_message(row) for row in rows),
        )

    async def save_review(
        self, conversation_id: UUID, payload: SaveReviewRequest
    ) -> ConversationReview:
        await set_tenant_context(self._session, self._context.tenant_id)
        categories = tuple(sorted(set(payload.categories)))
        labels = tuple(sorted(set(payload.labels)))
        if not categories or not labels:
            raise _conversation_error("conversation_review_incomplete", status=422)
        parameters = {
            "id": new_uuid7(),
            "tenant": self._context.tenant_id,
            "conversation": conversation_id,
            "expected": payload.expected_revision,
            "categories": categories,
            "labels": labels,
            "note": payload.note,
            "admin": self._context.actor_id,
        }
        statement = (
            text(
                "INSERT INTO public.conversation_reviews "
                "(id,tenant_id,conversation_id,revision,categories,labels,note,"
                "reviewed_by_admin_id) SELECT :id,:tenant,:conversation,1,"
                ":categories,:labels,:note,:admin WHERE :expected=0 "
                "ON CONFLICT (tenant_id,conversation_id) DO NOTHING RETURNING "
                "id,conversation_id,revision,categories,labels,note,"
                "reviewed_by_admin_id,updated_at"
            )
            if payload.expected_revision == 0
            else text(
                "UPDATE public.conversation_reviews SET revision=revision+1,"
                "categories=:categories,labels=:labels,note=:note,"
                "reviewed_by_admin_id=:admin,updated_at=now() "
                "WHERE tenant_id=:tenant AND conversation_id=:conversation "
                "AND revision=:expected RETURNING id,conversation_id,revision,"
                "categories,labels,note,reviewed_by_admin_id,updated_at"
            )
        ).bindparams(
            bindparam("categories", type_=ARRAY(TEXT)),
            bindparam("labels", type_=ARRAY(TEXT)),
        )
        row = (
            (await self._session.execute(statement, parameters))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _conversation_error("conversation_review_stale")
        review = ConversationReview.model_validate(dict(row))
        await AuditService(self._session).record(
            context=self._context,
            event_type="conversation.review_saved",
            entity_type="conversation",
            entity_id=conversation_id,
            payload={"categories": categories, "labels": labels},
        )
        return review

    async def export_eval_draft(
        self, conversation_id: UUID, reason: str
    ) -> EvalCaseDraft:
        detail = await self.detail(conversation_id)
        inbound = next(
            (
                message
                for message in reversed(detail.messages)
                if message.sender_type == "customer"
            ),
            None,
        )
        assistant = next(
            (
                message
                for message in reversed(detail.messages)
                if message.sender_type == "ai"
            ),
            None,
        )
        if inbound is None or assistant is None:
            raise _conversation_error("conversation_eval_pair_required", status=422)
        tool_names = tuple(
            sorted(
                {
                    str(call.get("tool_name"))
                    for call in _objects(assistant.runtime_metadata.get("tool_calls"))
                    if isinstance(call.get("tool_name"), str)
                }
            )
        )
        capabilities = tuple(sorted({name.partition(".")[0] for name in tool_names}))
        draft_id = new_uuid7()
        case_id = f"review-{str(draft_id).replace('-', '')[:20]}"
        payload: dict[str, object] = {
            "schema_version": 1,
            "case_id": case_id,
            "input_turn": {
                "message": _anonymize(inbound.text),
                "active_capabilities": capabilities,
                "permitted_tools": tool_names,
                "relevant_capabilities": capabilities,
            },
            "fixture_setup": {
                "fake_outputs": [_anonymize(assistant.text)],
                "tools": [
                    {
                        "name": name,
                        "capability": name.partition(".")[0],
                        "description": "Sanitized conversation review fixture.",
                        "input_schema": {"type": "object", "properties": {}},
                        "active": True,
                    }
                    for name in tool_names
                ],
            },
            "expected": {
                "response_required": True,
                "selected_tools": list(tool_names),
                "persisted_result": True,
                "credentials_absent": True,
            },
            "graders": [
                "response_exists",
                "selected_tools",
                "persisted_result",
                "credentials_absent",
            ],
            "tags": sorted(
                {
                    "conversation-review",
                    *[label.lower() for label in detail.conversation.review.labels],
                }
                if detail.conversation.review
                else {"conversation-review"}
            ),
        }
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO public.eval_case_drafts "
                        "(id,tenant_id,conversation_id,case_id,schema_version,payload,"
                        "created_by_admin_id) VALUES (:id,:tenant,:conversation,:case,1,"
                        ":payload,:admin) RETURNING id,conversation_id,case_id,"
                        "schema_version,payload,status,created_at"
                    ).bindparams(bindparam("payload", type_=JSONB)),
                    {
                        "id": draft_id,
                        "tenant": self._context.tenant_id,
                        "conversation": conversation_id,
                        "case": case_id,
                        "payload": payload,
                        "admin": self._context.actor_id,
                    },
                )
            )
            .mappings()
            .one()
        )
        await AuditService(self._session).record(
            context=self._context,
            event_type="eval_case_draft.exported",
            entity_type="eval_case_draft",
            entity_id=draft_id,
            payload={"conversation_id": str(conversation_id), "reason": reason},
        )
        return EvalCaseDraft.model_validate(dict(row))

    async def run(self, payload: TestRunRequest) -> TestRunInspector:
        await set_tenant_context(self._session, self._context.tenant_id)
        if payload.mode == "REAL_TEST_ENVIRONMENT":
            raise _conversation_error("real_test_environment_required")
        agent_row = (
            (
                await self._session.execute(
                    text(
                        "SELECT version.id,version.state,version.compiled_digest,"
                        "version.configuration FROM public.agent_spec_versions AS version "
                        "WHERE version.tenant_id=:tenant ORDER BY version.version_number "
                        "DESC LIMIT 1"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if agent_row is None:
            raise _conversation_error("agent_draft_required")
        config = cast(dict[str, object], agent_row["configuration"])
        digest = (
            agent_row["compiled_digest"]
            or sha256(
                json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        knowledge_row = (
            (
                await self._session.execute(
                    text(
                        "SELECT id,state,digest FROM public.knowledge_versions "
                        "WHERE tenant_id=:tenant ORDER BY version_number DESC LIMIT 1"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        intent, capability, tool, high_risk = _classify(payload.message)
        tools: tuple[dict[str, object], ...] = (
            (
                {
                    "name": tool,
                    "status": "SIMULATED",
                    "arguments": {"fixture": "sandbox"},
                    "result": {"ok": True, "external_effect": False},
                },
            )
            if tool
            else ()
        )
        trace_id = new_uuid7()
        created_at = datetime.now(UTC)
        sources: tuple[dict[str, object], ...] = ()
        if knowledge_row is not None:
            sources = (
                {
                    "knowledge_version_id": str(knowledge_row["id"]),
                    "authority": "TEST_FIXTURE",
                },
            )
        return TestRunInspector(
            id=new_uuid7(),
            tenant_id=self._context.tenant_id,
            mode=payload.mode,
            simulated=True,
            response=(
                "Simulated response: the request was understood and no Production "
                "connector was called."
            ),
            agent_spec={
                "id": str(agent_row["id"]),
                "digest": digest,
                "state": agent_row["state"],
            },
            knowledge=(
                None
                if knowledge_row is None
                else {
                    "id": str(knowledge_row["id"]),
                    "digest": knowledge_row["digest"],
                    "state": knowledge_row["state"],
                }
            ),
            intent=intent,
            capability=capability,
            identity={"required_level": 1, "status": "SIMULATED_VERIFIED"},
            tools=tools,
            sources=sources,
            action={
                "name": tool or "none",
                "status": "SIMULATED" if tool else "NOT_REQUIRED",
                "external_effect": False,
            },
            approval={
                "required": high_risk,
                "status": "SIMULATED" if high_risk else "NOT_REQUIRED",
            },
            usage={
                "model_tokens": len(payload.message.split()) + 12,
                "messages": 2,
                "external_requests": 0,
                "tool_calls": len(tools),
                "cost": {"amount": "0.000000", "currency": "USD", "kind": "SIMULATED"},
            },
            latency_ms=1,
            trace_id=trace_id,
            created_at=created_at,
        )

    async def _eval_drafts(self) -> tuple[EvalCaseDraft, ...]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id,conversation_id,case_id,schema_version,payload,status,"
                        "created_at FROM public.eval_case_drafts WHERE tenant_id=:tenant "
                        "ORDER BY created_at DESC,id DESC LIMIT 100"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(EvalCaseDraft.model_validate(dict(row)) for row in rows)


def _overview(row: object) -> ConversationOverview:
    values = cast(dict[str, object], row)
    review = None
    if values["review_id"] is not None:
        review = ConversationReview.model_validate(
            {
                "id": values["review_id"],
                "conversation_id": values["id"],
                "revision": values["revision"],
                "categories": values["categories"],
                "labels": values["labels"],
                "note": values["note"],
                "reviewed_by_admin_id": values["reviewed_by_admin_id"],
                "updated_at": values["updated_at"],
            }
        )
    customer = str(values["customer_wa_id"])
    return ConversationOverview(
        id=cast(UUID, values["id"]),
        customer_reference=f"Customer ••••{customer[-4:]}",
        control_state=str(values["control_state"]),
        message_count=cast(int, values["message_count"]),
        opened_at=cast(datetime, values["opened_at"]),
        latest_message_at=cast(datetime | None, values["latest_message_at"]),
        review=review,
    )


def _timeline_message(row: object) -> TimelineMessage:
    values = cast(dict[str, object], row)
    content = values["content"]
    text_value = "[Non-text message]"
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        text_value = content["text"]
    return TimelineMessage(
        id=cast(UUID, values["id"]),
        direction=str(values["direction"]),
        sender_type=str(values["sender_type"]),
        message_type=str(values["message_type"]),
        text=text_value,
        occurred_at=cast(datetime, values["provider_timestamp"]),
        agent_spec_id=cast(UUID | None, values["agent_spec_id"]),
        agent_spec_version=cast(str | None, values["agent_spec_version"]),
        runtime_metadata=cast(dict[str, object], values["runtime_metadata"]),
    )


def _objects(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _anonymize(value: str) -> str:
    sanitized = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[email]", value)
    sanitized = re.sub(r"\+?\d[\d\s().-]{6,}\d", "[phone]", sanitized)
    return sanitized[:4_000].strip() or "[anonymized message]"


def _classify(message: str) -> tuple[str, str, str | None, bool]:
    normalized = message.lower()
    if "cancel" in normalized and "order" in normalized:
        return (
            "request_order_cancellation",
            "orders",
            "orders.request_order_cancellation",
            True,
        )
    if "order" in normalized:
        return "order_status", "orders", "orders.get_status", False
    if "appointment" in normalized or "cita" in normalized:
        return (
            "check_availability",
            "appointments",
            "appointments.check_availability",
            False,
        )
    if "return" in normalized or "claim" in normalized:
        return "create_claim", "returns_claims", "returns_claims.get_case_status", False
    return "general_question", "customer_service", None, False


def _context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
    )


def _conversation_error(code: str, *, status: int = 409) -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/conversation-review",
        title="Conversation Review Unavailable",
        status=status,
        detail="The requested conversation review operation could not be completed.",
        code=code,
    )
