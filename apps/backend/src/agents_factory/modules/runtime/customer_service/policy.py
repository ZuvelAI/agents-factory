from __future__ import annotations

import re
from dataclasses import dataclass

from agents_factory.modules.runtime.customer_service.language import (
    ResponseLanguage,
    detect_response_language,
)
from agents_factory.modules.runtime.customer_service.scope import (
    ScopeDecision,
    classify_scope,
)


_DISCLOSURE_QUESTION = re.compile(
    r"(?i)\b(?:are you (?:a )?(?:bot|human|ai)|eres (?:un |una )?"
    r"(?:bot|humano|humana|ia)|hablo con (?:una )?persona|automated)\b"
)
_DISCLOSURE_TERMS = {
    "es": re.compile(
        r"(?i)\b(?:asistente virtual|automatizad[oa]|inteligencia artificial|ia)\b"
    ),
    "en": re.compile(
        r"(?i)\b(?:virtual assistant|automated|artificial intelligence|ai)\b"
    ),
}
_HUMAN_IMPERSONATION = re.compile(
    r"(?i)\b(?:soy (?:un |una )?human[oa]|i am (?:a )?human)\b"
)


@dataclass(frozen=True, slots=True)
class CustomerServicePolicyDecision:
    scope: ScopeDecision
    language: ResponseLanguage
    disclose_automation: bool


def evaluate_customer_message(message: str) -> CustomerServicePolicyDecision:
    return CustomerServicePolicyDecision(
        scope=classify_scope(message),
        language=detect_response_language(message),
        disclose_automation=_DISCLOSURE_QUESTION.search(message) is not None,
    )


def automation_disclosure(*, language: ResponseLanguage, business_name: str) -> str:
    if language == "es":
        return (
            f"Soy el asistente virtual automatizado de {business_name}. "
            "Puedo ayudarte con las operaciones disponibles y pedir apoyo humano "
            "cuando esté configurado."
        )
    return (
        f"I am {business_name}'s automated virtual assistant. I can help with "
        "available operations and request human support when it is configured."
    )


def response_has_truthful_disclosure(
    response: str, *, language: ResponseLanguage
) -> bool:
    return (
        _DISCLOSURE_TERMS[language].search(response) is not None
        and _HUMAN_IMPERSONATION.search(response) is None
    )
