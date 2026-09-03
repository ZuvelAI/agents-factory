from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp.outbound_service import ApprovedTemplateRequired


TemplateStatus = Literal["APPROVED", "PENDING", "REJECTED", "PAUSED", "DISABLED"]
TemplateCategory = Literal["UTILITY", "MARKETING", "AUTHENTICATION"]
_VARIABLE_NAME = re.compile(r"[a-z][a-z0-9_]{0,99}")


class TemplatePolicyViolation(DomainError):
    def __init__(self) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/template-policy-violation",
            title="WhatsApp Template Policy Violation",
            status=409,
            detail="The WhatsApp template binding is invalid.",
            code="template_policy_violation",
        )


@dataclass(frozen=True, slots=True)
class SyncedWhatsAppTemplate:
    provider_template_id: str
    name: str
    language: str
    status: TemplateStatus
    category: TemplateCategory
    variable_names: tuple[str, ...]

    def __post_init__(self) -> None:
        bounded = (
            self.provider_template_id.strip() == self.provider_template_id
            and self.name.strip() == self.name
            and self.language.strip() == self.language
            and bool(self.provider_template_id)
            and bool(self.name)
            and bool(self.language)
        )
        valid_variables = len(set(self.variable_names)) == len(
            self.variable_names
        ) and all(_VARIABLE_NAME.fullmatch(name) for name in self.variable_names)
        if not bounded or not valid_variables:
            raise ValueError("invalid synchronized WhatsApp template")


class TemplateService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        context: TenantContext,
    ) -> None:
        self._session_factory = session_factory
        self._context = context

    async def sync(
        self,
        *,
        whatsapp_account_id: UUID,
        templates: Sequence[SyncedWhatsAppTemplate],
    ) -> None:
        async with self._session_factory.begin() as session:
            await _prepare_app_session(session, self._context.tenant_id)
            account_exists = await session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM public.whatsapp_accounts "
                    "WHERE tenant_id = :tenant_id AND id = :account_id "
                    "AND status = 'active')"
                ),
                {
                    "tenant_id": self._context.tenant_id,
                    "account_id": whatsapp_account_id,
                },
            )
            if account_exists is not True:
                raise TemplatePolicyViolation
            for template in templates:
                await session.execute(
                    text(
                        "INSERT INTO public.whatsapp_templates "
                        "(id, tenant_id, whatsapp_account_id, provider_template_id, "
                        "name, language, status, category, variable_names, synced_at) "
                        "VALUES (:id, :tenant_id, :account_id, :provider_id, :name, "
                        ":language, :status, :category, :variables, now()) "
                        "ON CONFLICT (tenant_id, whatsapp_account_id, "
                        "provider_template_id) DO UPDATE SET name = excluded.name, "
                        "language = excluded.language, status = excluded.status, "
                        "category = excluded.category, "
                        "variable_names = excluded.variable_names, "
                        "synced_at = now(), updated_at = now()"
                    ).bindparams(bindparam("variables", type_=JSONB)),
                    {
                        "id": new_uuid7(),
                        "tenant_id": self._context.tenant_id,
                        "account_id": whatsapp_account_id,
                        "provider_id": template.provider_template_id,
                        "name": template.name,
                        "language": template.language,
                        "status": template.status,
                        "category": template.category,
                        "variables": list(template.variable_names),
                    },
                )
            await AuditService(session).record(
                context=self._context,
                event_type="whatsapp.templates.synced",
                entity_type="whatsapp_account",
                entity_id=whatsapp_account_id,
                payload={"template_count": len(templates)},
            )

    async def prepare_proactive(
        self,
        *,
        whatsapp_account_id: UUID,
        recipient_wa_id: str,
        template_name: str,
        language: str,
        variables: Mapping[str, str],
        idempotency_key: str,
        conversation_id: UUID | None = None,
    ) -> UUID:
        now = datetime.now(UTC)
        if (
            not recipient_wa_id.strip()
            or recipient_wa_id.strip() != recipient_wa_id
            or not idempotency_key.strip()
            or idempotency_key.strip() != idempotency_key
        ):
            raise TemplatePolicyViolation
        async with self._session_factory.begin() as session:
            await _prepare_app_session(session, self._context.tenant_id)
            if conversation_id is not None:
                allowed = await session.scalar(
                    text(
                        "SELECT id FROM public.conversations WHERE tenant_id = :tenant AND id = :conversation AND whatsapp_account_id = :account AND customer_wa_id = :recipient AND control_state = 'AI_ACTIVE' FOR UPDATE"
                    ),
                    {
                        "tenant": self._context.tenant_id,
                        "conversation": conversation_id,
                        "account": whatsapp_account_id,
                        "recipient": recipient_wa_id,
                    },
                )
                if allowed is None:
                    raise TemplatePolicyViolation
            existing_id = await session.scalar(
                text(
                    "SELECT id FROM public.outbound_messages "
                    "WHERE tenant_id = :tenant_id "
                    "AND idempotency_key = :idempotency_key"
                ),
                {
                    "tenant_id": self._context.tenant_id,
                    "idempotency_key": idempotency_key,
                },
            )
            if isinstance(existing_id, UUID):
                return existing_id
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT template.id, template.status, "
                            "template.variable_names "
                            "FROM public.whatsapp_templates AS template "
                            "JOIN public.whatsapp_accounts AS account "
                            "ON account.tenant_id = template.tenant_id "
                            "AND account.id = template.whatsapp_account_id "
                            "WHERE template.tenant_id = :tenant_id "
                            "AND template.whatsapp_account_id = :account_id "
                            "AND template.name = :name "
                            "AND template.language = :language "
                            "AND account.status = 'active'"
                        ),
                        {
                            "tenant_id": self._context.tenant_id,
                            "account_id": whatsapp_account_id,
                            "name": template_name,
                            "language": language,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise TemplatePolicyViolation
            if row["status"] != "APPROVED":
                raise ApprovedTemplateRequired
            variable_names = row["variable_names"]
            if (
                not isinstance(variable_names, list)
                or not all(isinstance(name, str) for name in variable_names)
                or set(variable_names) != set(variables)
                or any(
                    not isinstance(value, str)
                    or not value.strip()
                    or value != value.strip()
                    or len(value) > 1000
                    for value in variables.values()
                )
            ):
                raise TemplatePolicyViolation
            ordered_names = cast(list[str], variable_names)
            body_parameters = [variables[name] for name in ordered_names]
            payload = {
                "template_name": template_name,
                "language": language,
                "variable_names": ordered_names,
                "body_parameters": body_parameters,
            }
            outbound_id = new_uuid7()
            created_id = await session.scalar(
                text(
                    "INSERT INTO public.outbound_messages "
                    "(id, tenant_id, conversation_id, whatsapp_account_id, whatsapp_template_id, "
                    "recipient_wa_id, kind, idempotency_key, payload, status, "
                    "status_history) VALUES (:id, :tenant_id, :conversation_id, :account_id, "
                    ":template_id, :recipient_wa_id, 'template', "
                    ":idempotency_key, :payload, 'PREPARED', :history) "
                    "ON CONFLICT (tenant_id, idempotency_key) DO UPDATE "
                    "SET idempotency_key = outbound_messages.idempotency_key "
                    "RETURNING id"
                ).bindparams(
                    bindparam("payload", type_=JSONB),
                    bindparam("history", type_=JSONB),
                ),
                {
                    "id": outbound_id,
                    "tenant_id": self._context.tenant_id,
                    "conversation_id": conversation_id,
                    "account_id": whatsapp_account_id,
                    "template_id": row["id"],
                    "recipient_wa_id": recipient_wa_id,
                    "idempotency_key": idempotency_key,
                    "payload": payload,
                    "history": [
                        {
                            "status": "PREPARED",
                            "occurred_at": now.isoformat(),
                            "source": "template_service",
                        }
                    ],
                },
            )
            if not isinstance(created_id, UUID):
                raise RuntimeError("outbound template identity was not returned")
            await OutboxService(session).enqueue(
                context=self._context,
                idempotency_key=f"whatsapp.outbound.send:{created_id}",
                topic="whatsapp.outbound.send",
                payload={
                    "aggregate_id": str(created_id),
                    "message_id": str(created_id),
                },
            )
            await AuditService(session).record(
                context=self._context,
                event_type="whatsapp.template_send.prepared",
                entity_type="outbound_message",
                entity_id=created_id,
                payload={
                    "whatsapp_account_id": str(whatsapp_account_id),
                    "template_name": template_name,
                    "language": language,
                    "variable_count": len(ordered_names),
                },
            )
            return created_id


async def _prepare_app_session(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(text("SET LOCAL ROLE agents_factory_app"))
    await set_tenant_context(session, tenant_id)
