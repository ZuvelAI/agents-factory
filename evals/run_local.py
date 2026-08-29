from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
for source_root in (
    REPOSITORY_ROOT,
    REPOSITORY_ROOT / "apps/backend/src",
):
    source = str(source_root)
    if source not in sys.path:
        sys.path.insert(0, source)

from pydantic import ValidationError  # noqa: E402

from agents_factory.modules.runtime.contracts import (  # noqa: E402
    AgentRuntime,
    AgentSpecSnapshot,
    AgentTurnInput,
    AgentTurnResult,
    ModelConfiguration,
    RuntimeLimits,
    RuntimeTraceMetadata,
    RuntimeTool,
    RuntimeUsage,
    ToolInvocationContext,
    TurnMessage,
)
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry  # noqa: E402
from agents_factory.modules.runtime.customer_service.policy import (  # noqa: E402
    evaluate_customer_message,
)
from evals.case_schema import EvalCase  # noqa: E402
from evals.graders import (  # noqa: E402
    GRADERS,
    EvalObservation,
    GradeResult,
    redact_artifact,
)


RUNNER_VERSION = "0.1.0"


class EvalSuiteError(ValueError):
    pass


class DuplicateEvalCase(EvalSuiteError):
    pass


@dataclass(frozen=True, slots=True)
class EvalCaseResult:
    case_id: str
    passed: bool
    graders: tuple[GradeResult, ...]
    observed: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class EvalRunSummary:
    schema_version: int
    runner_version: str
    seed: int
    passed: bool
    passed_cases: int
    failed_cases: int
    cases: tuple[EvalCaseResult, ...]


class DeterministicFakeRuntime(AgentRuntime):
    def __init__(self, *, outputs: tuple[str, ...], seed: int) -> None:
        self._outputs = outputs
        self._random = random.Random(seed)

    async def run(self, turn: AgentTurnInput) -> AgentTurnResult:
        output = self._outputs[self._random.randrange(len(self._outputs))]
        response_suffix = self._random.randrange(1_000_000)
        return AgentTurnResult(
            output_text=output,
            tool_calls=(),
            usage=RuntimeUsage(
                requests=1,
                input_tokens=len(turn.messages[-1].text.split()),
                cached_input_tokens=0,
                output_tokens=len(output.split()),
                reasoning_tokens=0,
                total_tokens=(
                    len(turn.messages[-1].text.split()) + len(output.split())
                ),
            ),
            provider_response_id=f"fake-{response_suffix:06d}",
        )


async def _fixture_tool_handler(
    context: ToolInvocationContext,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    _ = context
    return {"ok": True, "received_fields": sorted(arguments)}


def load_cases(path: Path) -> tuple[EvalCase, ...]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    paths = tuple(sorted(path.glob("*.jsonl"))) if path.is_dir() else (path,)
    for cases_path in paths:
        for line_number, raw_line in enumerate(
            cases_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not raw_line.strip():
                continue
            try:
                case = EvalCase.model_validate_json(raw_line)
            except ValidationError:
                raise EvalSuiteError(
                    f"invalid eval case at line {line_number}"
                ) from None
            if case.case_id in seen:
                raise DuplicateEvalCase(case.case_id)
            seen.add(case.case_id)
            cases.append(case)
    if not cases:
        raise EvalSuiteError("eval suite is empty")
    return tuple(cases)


async def run_cases(
    cases: Sequence[EvalCase],
    *,
    seed: int,
) -> EvalRunSummary:
    results: list[EvalCaseResult] = []
    for case in sorted(cases, key=lambda item: item.case_id):
        observation = await _run_case(case, seed=seed)
        grades = tuple(
            GRADERS[grader_name].grade(case=case, observation=observation)
            for grader_name in case.graders
        )
        results.append(
            EvalCaseResult(
                case_id=case.case_id,
                passed=all(grade.passed for grade in grades),
                graders=grades,
                observed=observation.artifact_data,
            )
        )
    passed_cases = sum(result.passed for result in results)
    return EvalRunSummary(
        schema_version=1,
        runner_version=RUNNER_VERSION,
        seed=seed,
        passed=passed_cases == len(results),
        passed_cases=passed_cases,
        failed_cases=len(results) - passed_cases,
        cases=tuple(results),
    )


async def _run_case(case: EvalCase, *, seed: int) -> EvalObservation:
    case_seed = int.from_bytes(
        hashlib.sha256(f"{seed}:{case.case_id}".encode()).digest()[:8],
        "big",
    )
    tenant_id = uuid5(NAMESPACE_URL, f"eval-tenant:{case.case_id}")
    conversation_id = uuid5(NAMESPACE_URL, f"eval-conversation:{case.case_id}")
    inbound_message_id = uuid5(NAMESPACE_URL, f"eval-message:{case.case_id}")
    spec_payload = json.dumps(
        case.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    spec = AgentSpecSnapshot(
        id=uuid5(NAMESPACE_URL, f"eval-spec:{case.case_id}"),
        tenant_id=tenant_id,
        version="eval-v0",
        digest=hashlib.sha256(spec_payload.encode()).hexdigest(),
        product="customer_service",
        product_version="1.0.0",
        instructions="Deterministic Customer Service eval fixture.",
        active_capabilities=frozenset(case.input_turn.active_capabilities),
        permitted_tools=frozenset(case.input_turn.permitted_tools),
        model=ModelConfiguration(),
        limits=RuntimeLimits(
            max_output_tokens=512, max_tool_calls=4, timeout_seconds=5
        ),
        active=True,
    )
    registry = RuntimeToolRegistry(
        RuntimeTool(
            name=tool.name,
            capability=tool.capability,
            description=tool.description,
            input_schema=tool.input_schema,
            handler=_fixture_tool_handler,
            active=tool.active,
        )
        for tool in case.fixture_setup.tools
    )
    selected_tools = registry.select(
        agent_spec=spec,
        relevant_capabilities=frozenset(case.input_turn.relevant_capabilities),
    )
    turn = AgentTurnInput(
        agent_spec=spec,
        messages=(
            TurnMessage(
                id=inbound_message_id,
                role="user",
                text=case.input_turn.message,
            ),
        ),
        tools=selected_tools,
        trace=RuntimeTraceMetadata(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
            correlation_id=uuid5(NAMESPACE_URL, f"eval-correlation:{case.case_id}"),
            agent_spec_id=spec.id,
            agent_spec_digest=spec.digest,
        ),
    )
    result = await DeterministicFakeRuntime(
        outputs=case.fixture_setup.fake_outputs,
        seed=case_seed,
    ).run(turn)
    policy = evaluate_customer_message(case.input_turn.message)
    in_memory_store: dict[UUID, AgentTurnResult] = {}
    in_memory_store[inbound_message_id] = result
    artifact: dict[str, object] = {
        "response_text": result.output_text,
        "selected_tools": [tool.name for tool in selected_tools],
        "persisted_result": inbound_message_id in in_memory_store,
        "provider_response_id": result.provider_response_id,
        "agent_spec_digest": spec.digest,
        "policy_classification": policy.scope,
        "response_language": policy.language,
    }
    return EvalObservation(
        response_text=result.output_text,
        selected_tools=tuple(tool.name for tool in selected_tools),
        persisted_result=inbound_message_id in in_memory_store,
        artifact_data=artifact,
        policy_classification=policy.scope,
        response_language=policy.language,
    )


def write_summary(summary: EvalRunSummary, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = redact_artifact(asdict(summary))
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic Agents Factory evals"
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    arguments = parser.parse_args(argv)
    try:
        cases = load_cases(arguments.cases)
        summary = asyncio.run(run_cases(cases, seed=arguments.seed))
        write_summary(summary, arguments.output)
    except (EvalSuiteError, OSError, ValidationError) as error:
        print(f"eval v0 failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(f"eval v0: {summary.passed_cases} passed, {summary.failed_cases} failed")
    return 0 if summary.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
