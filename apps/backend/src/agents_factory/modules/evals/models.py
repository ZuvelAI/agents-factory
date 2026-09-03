from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


HardBlocker = Literal[
    "CROSS_TENANT_ACCESS",
    "SENSITIVE_ACTION_WITHOUT_AUTHORIZATION",
    "CONFIRMATION_BYPASS",
    "HIGH_APPROVAL_BYPASS",
    "SECRET_EXPOSURE",
    "AI_REPLY_DURING_HUMAN_ACTIVE",
    "FALSE_SUCCESS_AFTER_UNCERTAIN_WRITE",
]


class EvalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class QualityGateRunRequest(EvalModel):
    agent_spec_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = 1701
    suites: tuple[
        Literal[
            "global",
            "security",
            "tenant_isolation",
            "human_control",
            "failure_handling",
            "appointments",
            "orders",
            "returns_claims",
            "runtime_smoke",
            "release_acceptance",
        ],
        ...,
    ] = (
        "global",
        "security",
        "tenant_isolation",
        "human_control",
        "failure_handling",
        "appointments",
        "orders",
        "returns_claims",
        "runtime_smoke",
        "release_acceptance",
    )
    hard_blockers: tuple[HardBlocker, ...] = ()


class QualityGateDecision(EvalModel):
    id: UUID
    eval_run_id: UUID
    passed: bool
    agent_spec_digest: str
    knowledge_digest: str
    code_digest: str
    hard_blockers: tuple[HardBlocker, ...]
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    runner_version: str
    decided_at: datetime


class QualityGateOverview(EvalModel):
    available: Literal[True] = True
    latest: QualityGateDecision | None
    exact_version_required: Literal[True] = True
