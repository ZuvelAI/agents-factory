"""Pure, credential-free projection of stored versions into operator-facing facts."""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from .workspace_models import (
    AgentConfigurationView,
    AgentSummary,
    ChannelSummary,
    FeatureSummary,
)
from .configuration_models import AgentEditableConfiguration


def editable_configuration_view(config: dict[str, Any]) -> AgentConfigurationView:
    draft = AgentEditableConfiguration.model_validate(config)
    return AgentConfigurationView(
        name=draft.agent.agent_name or "Agente sin nombre",
        purpose=draft.purpose or None,
        tone=draft.agent.tone,
        instructions=draft.agent.instructions or None,
        model=draft.agent.model,
        knowledge_summary=draft.knowledge.approved_summary or None,
        capabilities=[
            FeatureSummary(
                key=key,
                label=key,
                availability="unavailable",
                enabled=False,
                reason="Requiere conexión y validación operativa.",
            )
            for key in draft.capabilities.selected_capabilities
        ],
        integrations=[
            FeatureSummary(
                key=key,
                label=key,
                availability="unavailable",
                enabled=False,
                reason="Conexión no verificada; no habilitada por este borrador.",
            )
            for key in draft.integrations.required_connectors
        ],
    )


def configuration_view(config: dict[str, Any] | None) -> AgentConfigurationView | None:
    if config is None:
        return None
    persona = config.get("persona") or {}
    context = config.get("approved_business_context") or {}
    return AgentConfigurationView(
        name=persona.get("business_name") or "Agente sin nombre",
        instructions=persona.get("instructions"),
        model=(config.get("model") or {}).get("model"),
        knowledge_summary=context.get("approved_summary"),
        capabilities=[
            FeatureSummary(
                key=c["name"],
                label=c["name"],
                availability="unknown",
                enabled=False,
                reason="Permiso declarado; disponibilidad de ejecución no verificada.",
            )
            for c in config.get("capabilities", [])
        ],
        integrations=[
            FeatureSummary(
                key=c["connector"],
                label=c["connector"],
                availability="unknown",
                enabled=False,
                reason="Referencia declarada; conexión no verificada.",
            )
            for c in config.get("connector_bindings", [])
        ],
    )


def channel_summary(row: dict[str, Any]) -> ChannelSummary:
    checked = row["last_health_checked_at"]
    if isinstance(checked, str):
        checked = datetime.fromisoformat(checked)
    fresh = checked is not None and timedelta(0) <= datetime.now(
        timezone.utc
    ) - checked <= timedelta(minutes=15)
    state: Literal["unknown", "connected", "disconnected", "review_required"] = (
        "unknown"
    )
    if row["status"] != "active":
        state = "disconnected"
    elif fresh:
        if row["health_status"] == "HEALTHY":
            state = "connected"
        elif row["health_status"] in ("REAUTH_REQUIRED", "ERROR"):
            state = "review_required"
    return ChannelSummary(
        account_id=row["id"],
        version_id=row.get("version_id"),
        display_number="+" + row["display_phone_digits"]
        if row["display_phone_digits"]
        else None,
        connection_status=state,
        checked_at=checked,
    )


def agent_summary(row: dict[str, Any]) -> AgentSummary:
    channels = [channel_summary(c) for c in row["channels"]]
    return AgentSummary(
        id=row["id"],
        tenant_id=row["tenant_id"],
        display_name=row["published_name"]
        or row["draft_name"]
        or "Agente sin configurar",
        published_name=row["published_name"],
        published_version_id=row["published_id"],
        draft_version_id=row["draft_id"],
        has_pending_changes=row["draft_id"] is not None
        or row.get("editable_revision") is not None,
        purpose=row.get("purpose"),
        execution_status="unknown" if channels else "unassigned",
        channel_accounts=channels,
    )
