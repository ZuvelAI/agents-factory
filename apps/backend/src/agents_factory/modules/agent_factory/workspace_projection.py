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


def pending_configuration_changes(
    *,
    has_candidate: bool,
    editable_revision: int | None,
    editable_company_revision: int | None,
    current_company_revision: int | None,
    published_draft_revision: int | None,
    published_company_revision: int | None,
) -> bool:
    """Compare the draft with publication provenance, not with each account binding.

    Older versions may intentionally remain on other numbers. An editable draft
    persists after publishing and is not itself evidence of unpublished changes.
    Missing provenance (including legacy publications) remains pending safely.
    """
    if has_candidate:
        return True
    if editable_revision is None:
        return False
    return (
        editable_revision != published_draft_revision
        or editable_company_revision is None
        or editable_company_revision != published_company_revision
        or editable_company_revision != current_company_revision
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
        has_pending_changes=pending_configuration_changes(
            has_candidate=row["draft_id"] is not None,
            editable_revision=row.get("editable_revision"),
            editable_company_revision=row.get("editable_company_revision"),
            current_company_revision=row.get("current_company_revision"),
            published_draft_revision=row.get("published_draft_revision"),
            published_company_revision=row.get("published_company_revision"),
        ),
        purpose=row.get("purpose"),
        execution_status="unknown" if channels else "unassigned",
        channel_accounts=channels,
    )
