from pydantic import Field

from agents_factory.modules.media.contracts import (
    MediaModel,
    NormalizedMediaObservation,
)


class Phone(MediaModel):
    phone: str | None = Field(default=None, max_length=100)
    wa_id: str | None = Field(default=None, max_length=100)
    type: str | None = Field(default=None, max_length=50)


class ContactName(MediaModel):
    formatted_name: str = Field(min_length=1, max_length=300)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    prefix: str | None = Field(default=None, max_length=50)
    suffix: str | None = Field(default=None, max_length=50)


class Contact(MediaModel):
    name: ContactName
    phones: tuple[Phone, ...] = Field(default=(), max_length=20)
    emails: tuple[dict[str, str], ...] = Field(default=(), max_length=20)
    addresses: tuple[dict[str, str], ...] = Field(default=(), max_length=20)
    urls: tuple[dict[str, str], ...] = Field(default=(), max_length=20)
    org: dict[str, str] = Field(default_factory=dict)
    birthday: str | None = Field(default=None, max_length=10)


class Contacts(MediaModel):
    contacts: tuple[Contact, ...] = Field(min_length=1, max_length=20)


def normalize_contacts(content: dict[str, object]) -> NormalizedMediaObservation:
    import json

    if len(json.dumps(content, ensure_ascii=False, allow_nan=False)) > 30000:
        raise ValueError("contacts_size_invalid")
    value = Contacts.model_validate(content)
    return NormalizedMediaObservation(
        kind="contacts",
        status="READY",
        fields=value.model_dump(mode="json", exclude_none=True),
    )
