from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from evals.case_schema import EvalCase, GraderName


_SECRET_PATTERN = re.compile(
    r"(?i)(?:sk-(?:proj-)?[a-z0-9_-]{12,}|bearer\s+[a-z0-9._-]{12,})"
)
_SENSITIVE_KEYS = (
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "credential",
    "password",
    "refresh_token",
    "secret",
)


@dataclass(frozen=True, slots=True)
class EvalObservation:
    response_text: str
    selected_tools: tuple[str, ...]
    persisted_result: bool
    artifact_data: Mapping[str, object]
    policy_classification: str | None = None
    response_language: str | None = None


@dataclass(frozen=True, slots=True)
class GradeResult:
    grader: GraderName
    passed: bool
    diagnostic: str


class EvalGrader(Protocol):
    name: GraderName

    def grade(
        self,
        *,
        case: EvalCase,
        observation: EvalObservation,
    ) -> GradeResult: ...


class ResponseExistsGrader:
    name: GraderName = "response_exists"

    def grade(
        self,
        *,
        case: EvalCase,
        observation: EvalObservation,
    ) -> GradeResult:
        actual = bool(observation.response_text.strip())
        passed = actual is case.expected.response_required
        return GradeResult(
            grader=self.name,
            passed=passed,
            diagnostic="response presence matched"
            if passed
            else "response presence differed",
        )


class SelectedToolsGrader:
    name: GraderName = "selected_tools"

    def grade(
        self,
        *,
        case: EvalCase,
        observation: EvalObservation,
    ) -> GradeResult:
        passed = observation.selected_tools == case.expected.selected_tools
        return GradeResult(
            grader=self.name,
            passed=passed,
            diagnostic="tool exposure matched" if passed else "tool exposure differed",
        )


class PersistedResultGrader:
    name: GraderName = "persisted_result"

    def grade(
        self,
        *,
        case: EvalCase,
        observation: EvalObservation,
    ) -> GradeResult:
        passed = observation.persisted_result is case.expected.persisted_result
        return GradeResult(
            grader=self.name,
            passed=passed,
            diagnostic=(
                "persistence expectation matched"
                if passed
                else "persistence expectation differed"
            ),
        )


class CredentialsAbsentGrader:
    name: GraderName = "credentials_absent"

    def grade(
        self,
        *,
        case: EvalCase,
        observation: EvalObservation,
    ) -> GradeResult:
        absent = not contains_credentials(observation.artifact_data)
        passed = absent is case.expected.credentials_absent
        return GradeResult(
            grader=self.name,
            passed=passed,
            diagnostic=(
                "credential boundary matched"
                if passed
                else "credential boundary differed"
            ),
        )


class PolicyClassificationGrader:
    name: GraderName = "policy_classification"

    def grade(
        self,
        *,
        case: EvalCase,
        observation: EvalObservation,
    ) -> GradeResult:
        passed = (
            case.expected.policy_classification is not None
            and observation.policy_classification == case.expected.policy_classification
        )
        return GradeResult(
            grader=self.name,
            passed=passed,
            diagnostic="policy classification matched"
            if passed
            else "policy classification differed",
        )


class ResponseLanguageGrader:
    name: GraderName = "response_language"

    def grade(
        self,
        *,
        case: EvalCase,
        observation: EvalObservation,
    ) -> GradeResult:
        passed = (
            case.expected.response_language is not None
            and observation.response_language == case.expected.response_language
        )
        return GradeResult(
            grader=self.name,
            passed=passed,
            diagnostic="response language matched"
            if passed
            else "response language differed",
        )


class TruthfulDisclosureGrader:
    name: GraderName = "truthful_disclosure"

    def grade(
        self,
        *,
        case: EvalCase,
        observation: EvalObservation,
    ) -> GradeResult:
        from agents_factory.modules.runtime.customer_service.policy import (
            response_has_truthful_disclosure,
        )

        expected = case.expected.truthful_disclosure
        language = observation.response_language
        actual = language in {"es", "en"} and response_has_truthful_disclosure(
            observation.response_text,
            language=language,  # type: ignore[arg-type]
        )
        passed = expected is not None and actual is expected
        return GradeResult(
            grader=self.name,
            passed=passed,
            diagnostic="automation disclosure matched"
            if passed
            else "automation disclosure differed",
        )


class AppointmentBehaviorGrader:
    name: GraderName = "appointment_behavior"

    def grade(self, *, case: EvalCase, observation: EvalObservation) -> GradeResult:
        passed = (
            case.expected.appointment_behavior is not None
            and observation.artifact_data.get("appointment_behavior")
            == case.expected.appointment_behavior
        )
        return GradeResult(
            grader=self.name,
            passed=passed,
            diagnostic="appointment gate matched"
            if passed
            else "appointment gate differed",
        )


GRADERS: dict[GraderName, EvalGrader] = {
    "appointment_behavior": AppointmentBehaviorGrader(),
    "response_exists": ResponseExistsGrader(),
    "selected_tools": SelectedToolsGrader(),
    "persisted_result": PersistedResultGrader(),
    "credentials_absent": CredentialsAbsentGrader(),
    "policy_classification": PolicyClassificationGrader(),
    "response_language": ResponseLanguageGrader(),
    "truthful_disclosure": TruthfulDisclosureGrader(),
}


def contains_credentials(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(fragment in normalized for fragment in _SENSITIVE_KEYS):
                return True
            if contains_credentials(nested):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(contains_credentials(nested) for nested in value)
    return isinstance(value, str) and _SECRET_PATTERN.search(value) is not None


def redact_artifact(value: object) -> object:
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            redacted[str(key)] = (
                "[REDACTED_SECRET]"
                if any(fragment in normalized for fragment in _SENSITIVE_KEYS)
                else redact_artifact(nested)
            )
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_artifact(nested) for nested in value]
    if isinstance(value, str):
        return _SECRET_PATTERN.sub("[REDACTED_SECRET]", value)
    return value
