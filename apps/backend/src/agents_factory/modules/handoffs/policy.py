import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from agents_factory.modules.handoffs.models import HandoffConfiguration, HandoffReason


def explicit_human_request(message: str) -> bool:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", message.lower())
        if not unicodedata.combining(char)
    ).strip()
    # Conservative admission: frustration/help/approval status are not consent.
    if re.search(r"\b(no|not|don't|do not|sin)\b", normalized):
        return False
    return bool(
        re.fullmatch(
            r"(?:por favor[, ]+|please[, ]+)?"
            r"(?:quiero hablar con (?:un humano|una persona|un asesor)|"
            r"necesito hablar con (?:un humano|una persona|un asesor)|"
            r"pasame con (?:un humano|una persona|un asesor)|hablar con una persona|"
            r"(?:i want to |i need to )?(?:talk|speak) to (?:a human|a person|an agent)|"
            r"human agent)"
            r"[.!? ]*(?:por favor|please)?[.!? ]*",
            normalized,
        )
    )


def escalation_reason(
    *,
    customer_text: str = "",
    mandatory_policy: bool = False,
    repeated_integration_failure: bool = False,
    consequential_action_unresolved: bool = False,
) -> HandoffReason | None:
    """Non-text flags are trusted backend policy outcomes, never model arguments."""
    if mandatory_policy:
        return HandoffReason.MANDATORY_ESCALATION
    if repeated_integration_failure:
        return HandoffReason.REPEATED_INTEGRATION_FAILURE
    if consequential_action_unresolved:
        return HandoffReason.CONSEQUENTIAL_ACTION_UNRESOLVED
    if explicit_human_request(customer_text):
        return HandoffReason.EXPLICIT_REQUEST
    return None


def within_support_hours(configuration: HandoffConfiguration, now: datetime) -> bool:
    if configuration.support_hours is None:
        return True
    local = now.astimezone(ZoneInfo(configuration.timezone))
    return any(
        window.weekday == local.weekday() and window.start <= local.time() < window.end
        for window in configuration.support_hours
    )


def waiting_copy(configuration: HandoffConfiguration, now: datetime) -> str:
    if not within_support_hours(configuration, now):
        return (
            "Tu solicitud de atención humana quedó registrada. Estamos fuera del "
            "horario de atención configurado; no hay una persona conectada confirmada."
        )
    return (
        "Tu solicitud de atención humana quedó registrada. "
        "Esto no confirma que haya una persona conectada en este momento."
    )
