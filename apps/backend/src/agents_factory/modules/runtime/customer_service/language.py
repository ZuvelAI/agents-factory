from __future__ import annotations

import re
from typing import Literal


ResponseLanguage = Literal["es", "en"]
_WORDS = re.compile(r"[a-záéíóúüñ']+", re.IGNORECASE)
_SPANISH = frozenset(
    {
        "ayuda",
        "cancelar",
        "cita",
        "cómo",
        "dónde",
        "el",
        "estado",
        "gracias",
        "hola",
        "mi",
        "necesito",
        "pedido",
        "por",
        "puedo",
        "quiero",
        "reclamo",
        "una",
    }
)
_ENGLISH = frozenset(
    {
        "appointment",
        "are",
        "bot",
        "can",
        "help",
        "hello",
        "human",
        "ignore",
        "instructions",
        "how",
        "i",
        "my",
        "need",
        "order",
        "please",
        "previous",
        "reveal",
        "secrets",
        "status",
        "the",
        "to",
        "where",
        "you",
    }
)


def detect_response_language(
    message: str, *, default: ResponseLanguage = "es"
) -> ResponseLanguage:
    words = tuple(word.lower() for word in _WORDS.findall(message))
    spanish_score = sum(word in _SPANISH for word in words)
    english_score = sum(word in _ENGLISH for word in words)
    if spanish_score == english_score:
        return default
    return "es" if spanish_score > english_score else "en"
