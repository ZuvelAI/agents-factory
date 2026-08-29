from __future__ import annotations

import re
from typing import Literal


ScopeDecision = Literal["IN_SCOPE", "REDIRECT", "SAFETY_INCIDENT"]
_SAFETY = re.compile(
    r"(?i)\b(?:ignore (?:all |previous )?instructions|system prompt|"
    r"reveal (?:the )?secrets?|matar|bomba|amenaza creíble|kill|credible threat)\b"
)
_BUSINESS = re.compile(
    r"(?i)\b(?:appointment|booking|cancel(?:lation)?|claim|customer support|"
    r"delivery|help|order|refund|return|service|shipping|status|tracking|"
    r"address|ayuda|cancelar|cita|devoluci[oó]n|domicilio|entrega|estado|"
    r"pedido|reclamo|reserva|servicio|soporte)\b"
)
_NON_BUSINESS = re.compile(
    r"(?i)\b(?:weather|forecast|football|movie|recipe|clima|f[uú]tbol|"
    r"pel[ií]cula|receta|lloviendo)\b"
)


def classify_scope(message: str) -> ScopeDecision:
    if _SAFETY.search(message):
        return "SAFETY_INCIDENT"
    if _BUSINESS.search(message):
        return "IN_SCOPE"
    if _NON_BUSINESS.search(message) or message.strip():
        return "REDIRECT"
    return "REDIRECT"
