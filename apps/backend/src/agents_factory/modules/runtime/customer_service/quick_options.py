from __future__ import annotations

from typing import Literal


QuickOptionLanguage = Literal["es", "en"]
_OPTIONS: dict[str, dict[QuickOptionLanguage, str]] = {
    "appointments": {"es": "Gestionar una cita", "en": "Manage an appointment"},
    "orders": {"es": "Consultar un pedido", "en": "Check an order"},
    "returns_claims": {
        "es": "Devoluciones y reclamos",
        "en": "Returns and claims",
    },
}


def build_quick_options(
    *,
    active_capabilities: frozenset[str],
    language: QuickOptionLanguage,
    handoff_enabled: bool,
    handoff_surface_available: bool,
) -> tuple[str, ...]:
    options = tuple(
        _OPTIONS[capability][language]
        for capability in sorted(active_capabilities)
        if capability in _OPTIONS
    )
    if handoff_enabled and handoff_surface_available:
        human = "Hablar con una persona" if language == "es" else "Talk to a person"
        return (*options, human)
    return options
