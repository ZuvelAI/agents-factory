from __future__ import annotations

import hashlib
import hmac
import re
from contextlib import asynccontextmanager
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import AsyncIterator, Mapping, cast
from uuid import UUID

import httpx
from pydantic import SecretStr, ValidationError

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.modules.whatsapp.contracts import (
    DeliveryStatus,
    InboundWhatsAppEvent,
    MetaAuthorizationSnapshot,
    MetaAccessTokenResolver,
    MetaHealthSnapshot,
    OutboundTemplateRequest,
    OutboundTextRequest,
    ProviderMessageResult,
    ProviderWebhookBatch,
    WhatsAppDeliveryStatusEvent,
    WhatsAppMessageType,
)
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.whatsapp.schemas import MetaWebhookPayload


_SIGNATURE_PATTERN = re.compile(r"sha256=([0-9a-f]{64})")
_SUPPORTED_MESSAGE_TYPES = frozenset(
    {"text", "audio", "image", "document", "location", "contacts", "video"}
)
_SUPPORTED_DELIVERY_STATUSES = frozenset(
    {"sent", "delivered", "read", "failed", "deleted"}
)


class InvalidWebhookPayload(DomainError):
    def __init__(self) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/invalid-webhook-payload",
            title="Invalid Webhook Payload",
            status=400,
            detail="The webhook payload is not supported.",
            code="invalid_webhook_payload",
        )


@dataclass(frozen=True, slots=True)
class MetaCloudApiProvider:
    app_secret: SecretStr = field(repr=False)
    access_tokens: MetaAccessTokenResolver | None = field(default=None, repr=False)
    http_client: httpx.AsyncClient | None = field(default=None, repr=False)
    graph_api_base_url: str | None = None

    def verify_signature(self, *, raw_body: bytes, signature: str) -> bool:
        match = _SIGNATURE_PATTERN.fullmatch(signature)
        if match is None:
            return False
        expected = hmac.new(
            self.app_secret.get_secret_value().encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(match.group(1), expected)

    def parse_webhook(
        self,
        payload: Mapping[str, object],
    ) -> ProviderWebhookBatch:
        try:
            parsed = MetaWebhookPayload.model_validate(payload)
        except ValidationError:
            raise InvalidWebhookPayload from None

        raw_payload = dict(payload)
        inbound_events: list[InboundWhatsAppEvent] = []
        delivery_statuses: list[WhatsAppDeliveryStatusEvent] = []
        for entry in parsed.entry:
            for change in entry.changes:
                if change.field != "messages":
                    continue
                for message in change.value.messages:
                    if message.type not in _SUPPORTED_MESSAGE_TYPES:
                        raise InvalidWebhookPayload
                    inbound_events.append(
                        InboundWhatsAppEvent(
                            waba_id=entry.id,
                            phone_number_id=change.value.metadata.phone_number_id,
                            whatsapp_message_id=message.id,
                            sender_wa_id=message.sender_wa_id,
                            message_type=cast(WhatsAppMessageType, message.type),
                            content=_normalized_content(message.model_dump()),
                            occurred_at=_provider_timestamp(message.timestamp),
                            raw_payload=raw_payload,
                        )
                    )
                for status in change.value.statuses:
                    if status.status not in _SUPPORTED_DELIVERY_STATUSES:
                        raise InvalidWebhookPayload
                    delivery_statuses.append(
                        WhatsAppDeliveryStatusEvent(
                            waba_id=entry.id,
                            phone_number_id=change.value.metadata.phone_number_id,
                            whatsapp_message_id=status.id,
                            recipient_wa_id=status.recipient_id,
                            status=cast(DeliveryStatus, status.status),
                            occurred_at=_provider_timestamp(status.timestamp),
                            raw_payload=raw_payload,
                            error_code=_delivery_error_code(status.errors),
                            cost_attribution=_cost_attribution(status.pricing),
                        )
                    )
        return ProviderWebhookBatch(
            inbound_events=tuple(inbound_events),
            delivery_statuses=tuple(delivery_statuses),
        )

    async def send_text(
        self,
        request: OutboundTextRequest,
    ) -> ProviderMessageResult:
        return await self._send(
            context=request.context,
            whatsapp_account_id=request.whatsapp_account_id,
            phone_number_id=request.phone_number_id,
            payload={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": request.recipient_wa_id,
                "type": "text",
                "text": {"preview_url": False, "body": request.body},
            },
        )

    async def send_template(
        self,
        request: OutboundTemplateRequest,
    ) -> ProviderMessageResult:
        template: dict[str, object] = {
            "name": request.template_name,
            "language": {"code": request.language},
        }
        if request.body_parameters:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": value}
                        for value in request.body_parameters
                    ],
                }
            ]
        return await self._send(
            context=request.context,
            whatsapp_account_id=request.whatsapp_account_id,
            phone_number_id=request.phone_number_id,
            payload={
                "messaging_product": "whatsapp",
                "to": request.recipient_wa_id,
                "type": "template",
                "template": template,
            },
        )

    async def _send(
        self,
        *,
        context: TenantContext,
        whatsapp_account_id: UUID,
        phone_number_id: str,
        payload: dict[str, object],
    ) -> ProviderMessageResult:
        if self.access_tokens is None or self.graph_api_base_url is None:
            return ProviderMessageResult(
                outcome="rejected",
                error_code="provider_not_configured",
            )
        resolved = await self.access_tokens.resolve(
            context=context,
            whatsapp_account_id=whatsapp_account_id,
        )
        try:
            access_token = resolved.reveal().decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return ProviderMessageResult(
                outcome="rejected",
                error_code="provider_credential_invalid",
            )
        url = f"{self.graph_api_base_url.rstrip('/')}/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            if self.http_client is None:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(url, headers=headers, json=payload)
            else:
                response = await self.http_client.post(
                    url,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException:
            return ProviderMessageResult(
                outcome="uncertain",
                error_code="provider_timeout",
            )
        except httpx.RequestError:
            return ProviderMessageResult(
                outcome="uncertain",
                error_code="provider_network_error",
            )
        return _provider_result(response)


@dataclass(frozen=True, slots=True)
class MetaEmbeddedSignupClient:
    """Backend-only Meta authorization exchange and asset verification."""

    app_id: str | None
    app_secret: SecretStr = field(repr=False)
    redirect_uri: str | None
    graph_api_base_url: str
    http_client: httpx.AsyncClient | None = field(default=None, repr=False)

    async def exchange_and_verify(
        self,
        *,
        code: str,
        business_id: str,
        waba_id: str,
        phone_number_id: str,
    ) -> MetaAuthorizationSnapshot:
        if self.app_id is None or self.redirect_uri is None:
            raise RuntimeError("Meta Embedded Signup is not configured")
        async with self._client() as client:
            token_response = await client.post(
                f"{self.graph_api_base_url.rstrip('/')}/oauth/access_token",
                data={
                    "client_id": self.app_id,
                    "client_secret": self.app_secret.get_secret_value(),
                    "redirect_uri": self.redirect_uri,
                    "code": code,
                },
            )
            token_payload = _required_json_mapping(token_response)
            access_token_value = token_payload.get("access_token")
            if not isinstance(access_token_value, str) or not access_token_value:
                raise RuntimeError("Meta authorization did not return a token")
            access_token = ResolvedSecret(access_token_value.encode("utf-8"))

            debug_response = await client.get(
                f"{self.graph_api_base_url.rstrip('/')}/debug_token",
                params={"input_token": access_token_value},
                headers={
                    "Authorization": (
                        f"Bearer {self.app_id}|{self.app_secret.get_secret_value()}"
                    )
                },
            )
            debug_payload = _required_json_mapping(debug_response)
            debug_data = debug_payload.get("data")
            if (
                not isinstance(debug_data, Mapping)
                or debug_data.get("is_valid") is not True
                or str(debug_data.get("app_id")) != self.app_id
            ):
                raise RuntimeError("Meta authorization is not valid")
            scopes = debug_data.get("scopes")
            granted_scopes = (
                frozenset(item for item in scopes if isinstance(item, str))
                if isinstance(scopes, list)
                else frozenset()
            )

            authorization_header = {"Authorization": f"Bearer {access_token_value}"}
            owned_wabas_response = await client.get(
                f"{self.graph_api_base_url.rstrip('/')}/{business_id}/"
                "owned_whatsapp_business_accounts",
                params={"fields": "id"},
                headers=authorization_header,
            )
            owned_wabas_payload = _required_json_mapping(owned_wabas_response)
            phone_response = await client.get(
                f"{self.graph_api_base_url.rstrip('/')}/{waba_id}/phone_numbers",
                params={"fields": "id"},
                headers=authorization_header,
            )
            phone_payload = _required_json_mapping(phone_response)

        expires_at = _optional_provider_expiry(debug_data.get("expires_at"))
        owned_wabas = owned_wabas_payload.get("data")
        owns_waba = isinstance(owned_wabas, list) and any(
            isinstance(item, Mapping) and item.get("id") == waba_id
            for item in owned_wabas
        )
        granular_targets = _granular_scope_targets(
            debug_data.get("granular_scopes"),
            scope="whatsapp_business_management",
        )
        if granular_targets is not None:
            owns_waba = owns_waba and (
                waba_id in granular_targets or business_id in granular_targets
            )
        phones = phone_payload.get("data")
        owns_phone = isinstance(phones, list) and any(
            isinstance(item, Mapping) and item.get("id") == phone_number_id
            for item in phones
        )
        return MetaAuthorizationSnapshot(
            access_token=access_token,
            business_id=business_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            granted_scopes=granted_scopes,
            token_expires_at=expires_at,
            owns_waba=owns_waba,
            owns_phone_number=owns_phone,
            # Never infer Coexistence from ordinary Cloud API access.
            coexistence_eligibility="UNKNOWN",
        )

    async def inspect_health(
        self,
        *,
        access_token: ResolvedSecret,
        waba_id: str,
        phone_number_id: str,
    ) -> MetaHealthSnapshot:
        try:
            token = access_token.reveal().decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return MetaHealthSnapshot(
                status="REAUTH_REQUIRED", error_code="provider_credential_invalid"
            )
        try:
            async with self._client() as client:
                response = await client.get(
                    f"{self.graph_api_base_url.rstrip('/')}/{waba_id}/phone_numbers",
                    params={"fields": "id"},
                    headers={"Authorization": f"Bearer {token}"},
                )
            if response.status_code in {401, 403}:
                return MetaHealthSnapshot(
                    status="REAUTH_REQUIRED", error_code="meta_authorization_revoked"
                )
            payload = _required_json_mapping(response)
            phones = payload.get("data")
            if isinstance(phones, list) and any(
                isinstance(item, Mapping) and item.get("id") == phone_number_id
                for item in phones
            ):
                return MetaHealthSnapshot(status="HEALTHY")
            return MetaHealthSnapshot(status="ERROR", error_code="meta_phone_missing")
        except (httpx.RequestError, RuntimeError):
            return MetaHealthSnapshot(status="ERROR", error_code="meta_health_failed")

    async def revoke(self, *, access_token: ResolvedSecret) -> None:
        try:
            token = access_token.reveal().decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise RuntimeError("Meta credential is invalid") from None
        async with self._client() as client:
            response = await client.delete(
                f"{self.graph_api_base_url.rstrip('/')}/me/permissions",
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code not in {200, 204}:
            raise RuntimeError("Meta authorization could not be revoked")

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.http_client is not None:
            yield self.http_client
            return
        async with httpx.AsyncClient(timeout=15.0) as client:
            yield client


def _provider_timestamp(value: str) -> datetime:
    try:
        seconds = int(value)
        if seconds < 0:
            raise ValueError
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, ValueError):
        raise InvalidWebhookPayload from None


def _normalized_content(message: Mapping[str, object]) -> dict[str, object]:
    message_type = message.get("type")
    if message_type != "text":
        return {}
    text_content = message.get("text")
    if not isinstance(text_content, dict):
        raise InvalidWebhookPayload
    body = text_content.get("body")
    if not isinstance(body, str) or not body.strip():
        raise InvalidWebhookPayload
    return {"text": body}


def _provider_result(response: httpx.Response) -> ProviderMessageResult:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if 200 <= response.status_code < 300:
        if isinstance(payload, Mapping):
            messages = payload.get("messages")
            if isinstance(messages, list) and messages:
                first = messages[0]
                if isinstance(first, Mapping):
                    provider_id = first.get("id")
                    if isinstance(provider_id, str) and provider_id.strip():
                        return ProviderMessageResult(
                            outcome="accepted",
                            provider_message_id=provider_id,
                        )
        return ProviderMessageResult(
            outcome="uncertain",
            error_code="invalid_provider_response",
        )
    error_code = f"http_{response.status_code}"
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            code = error.get("code")
            if isinstance(code, (int, str)):
                error_code = f"meta_{str(code)[:100]}"
    return ProviderMessageResult(
        outcome="uncertain" if response.status_code >= 500 else "rejected",
        error_code=error_code,
    )


def _required_json_mapping(response: httpx.Response) -> Mapping[str, object]:
    if not 200 <= response.status_code < 300:
        raise RuntimeError("Meta request failed")
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("Meta response was invalid") from None
    if not isinstance(payload, Mapping):
        raise RuntimeError("Meta response was invalid")
    return payload


def _optional_provider_expiry(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _granular_scope_targets(value: object, *, scope: str) -> frozenset[str] | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if not isinstance(item, Mapping) or item.get("scope") != scope:
            continue
        target_ids = item.get("target_ids")
        if not isinstance(target_ids, list):
            return frozenset()
        return frozenset(target for target in target_ids if isinstance(target, str))
    return None


def _delivery_error_code(errors: Sequence[object]) -> str | None:
    if not errors:
        return None
    code = getattr(errors[0], "code", None)
    if not isinstance(code, (int, str)):
        return None
    return f"meta_{str(code)[:100]}"


def _cost_attribution(pricing: object) -> dict[str, object]:
    if pricing is None:
        return {}
    result: dict[str, object] = {}
    for name in ("billable", "category", "pricing_model"):
        value = getattr(pricing, name, None)
        if isinstance(value, (bool, str)):
            result[name] = value
    return result
