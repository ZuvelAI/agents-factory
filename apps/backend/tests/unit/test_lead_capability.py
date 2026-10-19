"""Only the new opt-in internal operations bypass the connector requirement."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents_factory.modules.agent_factory.compiler import canonical_json
from agents_factory.modules.agent_factory.configuration_models import (
    AgentEditableConfiguration,
    DraftView,
)
from agents_factory.modules.agent_factory.configuration_projection import (
    project_configuration,
)
from agents_factory.modules.agent_factory.models import VersionReference
from agents_factory.modules.capabilities.registry import V1_CAPABILITY_REGISTRY
from agents_factory.modules.capabilities.service import (
    AgentSpecManifestError,
    CapabilityService,
)
from agents_factory.modules.integrations.registry import ConnectorRegistry
from agents_factory.modules.leads.capability import lead_capture_enabled
from apps.backend.tests.unit.agent_factory.test_onboarding_projection import (
    inputs,
    project,
    spec,
)


def draft_and_knowledge(enabled=None):
    config, knowledge = inputs()
    raw = config.model_dump(
        exclude={"company", "whatsapp", "test", "quality_gate", "production"}
    )
    if enabled is not None:
        raw["lead_capture"] = {"enabled": enabled}
    editable = AgentEditableConfiguration.model_validate(raw)
    draft = DraftView(
        tenant_id=knowledge.tenant_id,
        agent_instance_id=uuid4(),
        revision=1,
        company_revision=1,
        current_company_revision=1,
        company_update_available=False,
        company_snapshot=config.company,
        configuration=editable,
        provenance={},
        validation_issues=[],
        updated_at=datetime.now(UTC),
    )
    return draft, knowledge, config


def test_old_canonical_configuration_and_snapshot_are_unchanged():
    draft, knowledge, old = draft_and_knowledge()
    assert "lead_capture" not in draft.configuration.model_dump(mode="json")
    assert (
        canonical_json(project_configuration(draft, knowledge, "a" * 64)).json
        == canonical_json(project(old, knowledge)).json
    )
    disabled, _, _ = draft_and_knowledge(False)
    assert "lead_capture" not in disabled.configuration.model_dump(mode="json")


def test_enabled_capture_compiles_manifest_permissions_without_connector():
    draft, knowledge, _ = draft_and_knowledge(True)
    config = project_configuration(draft, knowledge, "a" * 64)
    assert config.capabilities == (
        VersionReference(name="lead_capture", version="1.0.0"),
    )
    assert config.permitted_tools == ("lead_capture.propose", "lead_capture.suppress")
    assert config.connector_bindings == ()
    version = spec(config, knowledge.tenant_id)
    validator = CapabilityService(
        capabilities=V1_CAPABILITY_REGISTRY, connectors=ConnectorRegistry()
    )
    validator.validate_agent_spec(version)
    runtime = version.to_runtime_snapshot(active=True)
    assert lead_capture_enabled(runtime)
    assert not lead_capture_enabled(replace(runtime, active=False))
    assert not lead_capture_enabled(
        replace(runtime, permitted_tools=frozenset({"lead_capture.propose"}))
    )
    assert not lead_capture_enabled(replace(runtime, active_capabilities=frozenset()))


def test_no_other_internal_operation_is_authorized():
    draft, knowledge, _ = draft_and_knowledge(True)
    config = project_configuration(draft, knowledge, "a" * 64)
    forged = config.model_copy(
        update={"permitted_tools": (*config.permitted_tools, "lead_capture.delete")}
    )
    validator = CapabilityService(
        capabilities=V1_CAPABILITY_REGISTRY, connectors=ConnectorRegistry()
    )
    with pytest.raises(AgentSpecManifestError):
        validator.validate_agent_spec(spec(forged, knowledge.tenant_id))


@pytest.mark.parametrize(
    "value", [{"enabled": "true"}, {"enabled": True, "crm": "external"}]
)
def test_lead_configuration_rejects_unknown_and_coerced_fields(value):
    with pytest.raises(ValidationError):
        AgentEditableConfiguration.model_validate({"lead_capture": value})


def test_workspace_shows_draft_intent_separately_from_published_permission():
    from agents_factory.modules.agent_factory.workspace_projection import (
        editable_configuration_view,
        configuration_view,
    )

    draft, knowledge, _ = draft_and_knowledge(True)
    preview = editable_configuration_view(draft.configuration.model_dump(mode="json"))
    (lead,) = preview.capabilities
    assert lead.key == "lead_capture" and lead.enabled
    assert "borrador" in lead.reason.lower()
    snapshot = project_configuration(draft, knowledge, "a" * 64).model_dump(mode="json")
    (current,) = configuration_view(snapshot).capabilities
    assert current.enabled and current.availability == "available"
    snapshot["permitted_tools"] = []
    assert not configuration_view(snapshot).capabilities[0].enabled
