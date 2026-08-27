from __future__ import annotations

from typing import NoReturn, SupportsIndex


class ResolvedSecret:
    """Backend-only plaintext wrapper that refuses implicit serialization."""

    __slots__ = ("_value",)

    def __init__(self, value: bytes) -> None:
        if not isinstance(value, bytes) or not value:
            raise TypeError("ResolvedSecret requires non-empty bytes")
        self._value = value

    def reveal(self) -> bytes:
        """Explicitly expose bytes only to the backend consumer that resolved it."""

        return self._value

    def __repr__(self) -> str:
        return "[REDACTED]"

    __str__ = __repr__

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("ResolvedSecret cannot be serialized")
