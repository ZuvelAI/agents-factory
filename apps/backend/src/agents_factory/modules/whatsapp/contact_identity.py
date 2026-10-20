"""Extract optional sender display data without treating opaque IDs as phones."""

import re
from collections.abc import Mapping

from .contracts import WhatsAppContactIdentity


def _label(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    if not value or len(value) > limit or any(ord(c) < 32 for c in value):
        return None
    return value


def meta_contact_identity(
    *, message: Mapping[str, object], contacts: object
) -> WhatsAppContactIdentity:
    """Match by an explicit sender identifier, not array order or display name."""
    explicit = {
        "wa_id": message.get("sender_phone_number"),
        "user_id": message.get("sender_user_id"),
        "parent_user_id": message.get("from_parent_user_id"),
    }
    matches = (
        [
            contact
            for contact in contacts
            if isinstance(contact, dict)
            and any(
                isinstance(value, str) and bool(value) and contact.get(key) == value
                for key, value in explicit.items()
            )
        ]
        if isinstance(contacts, list)
        else []
    )
    matches = [
        contact
        for contact in matches
        if not any(
            isinstance(value, str)
            and isinstance(contact.get(key), str)
            and contact[key] != value
            for key, value in explicit.items()
        )
    ]
    # Ambiguous metadata is not a reason to reject the customer's message.
    contact = matches[0] if len(matches) == 1 else {}
    profile = contact.get("profile")
    if not isinstance(profile, dict):
        profile = {}
    phone = message.get("sender_phone_number")
    # `from` explicitly denotes the phone; `from_user_id` is never a phone.
    phone = (
        "+" + phone
        if isinstance(phone, str) and re.fullmatch(r"[1-9][0-9]{6,14}", phone)
        else None
    )
    return WhatsAppContactIdentity(
        profile_name=_label(profile.get("name"), 1000),
        username=_label(profile.get("username"), 200)
        or _label(contact.get("username"), 200),
        phone_number=phone,
    )
