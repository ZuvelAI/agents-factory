"""Conservative template subset supported by the dashboard test sender."""

from agents_factory.modules.whatsapp.template_service import SyncedWhatsAppTemplate


def simple_approved_templates(payload: dict[str, object]) -> list[SyncedWhatsAppTemplate]:
    result: list[SyncedWhatsAppTemplate] = []
    data = payload.get("data", [])
    if not isinstance(data, list):
        return result
    for item in data:
        if not isinstance(item, dict) or item.get("status") != "APPROVED":
            continue
        components = item.get("components")
        if not isinstance(components, list) or not components:
            continue
        # This sender has no variable, media or button inputs. Do not pretend
        # those templates can be sent correctly without their required values.
        if any(
            not isinstance(c, dict)
            or c.get("type") not in {"HEADER", "BODY", "FOOTER"}
            or (c.get("type") == "HEADER" and c.get("format") != "TEXT")
            or not isinstance(c.get("text"), str)
            or "{{" in c["text"]
            for c in components
        ):
            continue
        if not any(c.get("type") == "BODY" for c in components):
            continue
        if not all(isinstance(item.get(k), str) for k in ("id", "name", "language")):
            continue
        category = item.get("category")
        if category not in ("UTILITY", "MARKETING", "AUTHENTICATION"):
            continue
        result.append(SyncedWhatsAppTemplate(
            provider_template_id=item["id"], name=item["name"],
            language=item["language"], status="APPROVED", category=category,
            variable_names=(),
        ))
    return result
