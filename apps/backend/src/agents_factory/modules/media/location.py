from pydantic import Field

from agents_factory.modules.media.contracts import (
    MediaModel,
    NormalizedMediaObservation,
)


class Location(MediaModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    name: str | None = Field(default=None, max_length=300)
    address: str | None = Field(default=None, max_length=1000)


def normalize_location(content: dict[str, object]) -> NormalizedMediaObservation:
    value = Location.model_validate(content)
    return NormalizedMediaObservation(
        kind="location", status="READY", fields=value.model_dump(exclude_none=True)
    )
