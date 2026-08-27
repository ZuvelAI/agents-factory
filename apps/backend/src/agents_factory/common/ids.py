import secrets
import time
from uuid import UUID


_TIMESTAMP_BITS = 48
_RANDOM_A_BITS = 12
_RANDOM_B_BITS = 62


def new_uuid7() -> UUID:
    """Create a UUID with the RFC 9562 UUIDv7 bit layout."""

    timestamp_ms = time.time_ns() // 1_000_000
    value = (timestamp_ms & ((1 << _TIMESTAMP_BITS) - 1)) << 80
    value |= 0x7 << 76
    value |= secrets.randbits(_RANDOM_A_BITS) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(_RANDOM_B_BITS)
    return UUID(int=value)


def correlation_id_from_header(value: str | None) -> UUID:
    """Accept only a canonical UUID header and replace all other input."""

    if value is None or len(value) != 36:
        return new_uuid7()

    try:
        identifier = UUID(value)
    except (AttributeError, ValueError):
        return new_uuid7()

    if str(identifier) != value.lower():
        return new_uuid7()
    return identifier
