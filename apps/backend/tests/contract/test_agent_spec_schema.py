from __future__ import annotations

import json
from pathlib import Path

from agents_factory.modules.agent_factory.models import AgentSpec


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = REPOSITORY_ROOT / "packages/agent-spec/agent_spec.schema.json"


def test_committed_agent_spec_schema_matches_pydantic_contract() -> None:
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert committed == AgentSpec.model_json_schema()
    assert committed["additionalProperties"] is False
    assert set(committed["required"]) == {
        "tenant_id",
        "agent_instance_id",
        "version_id",
        "version_number",
        "configuration",
    }


def test_schema_keeps_v1_product_model_and_languages_closed() -> None:
    schema = AgentSpec.model_json_schema()
    definitions = schema["$defs"]

    assert schema["properties"]["product"]["const"] == "Agent Customer Service"
    assert (
        definitions["AgentModelConfiguration"]["properties"]["model"]["const"]
        == "gpt-5.6-luna"
    )
    assert (
        definitions["AgentModelConfiguration"]["properties"]["reasoning_effort"][
            "const"
        ]
        == "low"
    )
    assert (
        definitions["LanguagePolicy"]["properties"]["default_locale"]["default"]
        == "es-CO"
    )
