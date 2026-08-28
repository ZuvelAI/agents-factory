from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.case_schema import EvalCase
from evals.run_local import (
    DuplicateEvalCase,
    load_cases,
    main,
    run_cases,
    write_summary,
)


def _case_payload(case_id: str = "runtime.smoke.es") -> dict[str, object]:
    return {
        "schema_version": 1,
        "case_id": case_id,
        "input_turn": {
            "message": "Necesito ayuda con mi pedido",
            "active_capabilities": ["orders"],
            "permitted_tools": ["orders.get_status"],
            "relevant_capabilities": ["orders"],
        },
        "fixture_setup": {
            "fake_outputs": ["Claro, revisemos tu pedido."],
            "tools": [
                {
                    "name": "orders.get_status",
                    "capability": "orders",
                    "description": "Read order status.",
                    "input_schema": {"type": "object", "properties": {}},
                    "active": True,
                }
            ],
        },
        "expected": {
            "response_required": True,
            "selected_tools": ["orders.get_status"],
            "persisted_result": True,
            "credentials_absent": True,
        },
        "graders": [
            "response_exists",
            "selected_tools",
            "persisted_result",
            "credentials_absent",
        ],
        "tags": ["runtime", "smoke", "es"],
    }


def test_schema_rejects_unknown_fields_and_graders() -> None:
    unknown_field = _case_payload()
    unknown_field["production_threshold"] = 0.99
    with pytest.raises(ValidationError):
        EvalCase.model_validate(unknown_field)

    unknown_grader = _case_payload()
    unknown_grader["graders"] = ["llm_judge"]
    with pytest.raises(ValidationError):
        EvalCase.model_validate(unknown_grader)


def test_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    cases_path = tmp_path / "duplicates.jsonl"
    encoded = json.dumps(_case_payload(), sort_keys=True)
    cases_path.write_text(f"{encoded}\n{encoded}\n", encoding="utf-8")

    with pytest.raises(DuplicateEvalCase):
        load_cases(cases_path)


@pytest.mark.asyncio
async def test_runner_is_seeded_ordered_reproducible_and_redacts_artifact(
    tmp_path: Path,
) -> None:
    spanish = EvalCase.model_validate(_case_payload("runtime.smoke.z_es"))
    english_payload = _case_payload("runtime.smoke.a_en")
    fixture = english_payload["fixture_setup"]
    assert isinstance(fixture, dict)
    fixture["fake_outputs"] = [
        "Here is a forbidden fixture token sk-proj-1234567890abcdef."
    ]
    english = EvalCase.model_validate(english_payload)

    first = await run_cases((spanish, english), seed=42)
    second = await run_cases((english, spanish), seed=42)

    assert first == second
    assert [result.case_id for result in first.cases] == [
        "runtime.smoke.a_en",
        "runtime.smoke.z_es",
    ]
    output_path = tmp_path / "latest.json"
    write_summary(first, output_path)
    artifact = output_path.read_text(encoding="utf-8")
    assert "sk-proj-" not in artifact
    assert "[REDACTED_SECRET]" in artifact


def test_cli_returns_nonzero_when_a_structured_expectation_fails(
    tmp_path: Path,
) -> None:
    payload = _case_payload()
    expected = payload["expected"]
    assert isinstance(expected, dict)
    expected["selected_tools"] = ["orders.cancel"]
    cases_path = tmp_path / "failing.jsonl"
    cases_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    exit_code = main(
        [
            "--cases",
            str(cases_path),
            "--output",
            str(tmp_path / "result.json"),
            "--seed",
            "7",
        ]
    )

    assert exit_code == 1
