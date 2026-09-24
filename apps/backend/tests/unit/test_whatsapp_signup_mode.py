import pytest
from pydantic import ValidationError

from agents_factory.common.errors import DomainError
from agents_factory.modules.whatsapp.router import (
    SignupStartRequest,
    _require_available_signup_mode,
)


def test_exclusive_mode_remains_available() -> None:
    _require_available_signup_mode("API_ONLY")


def test_coexistence_is_not_silently_converted_or_enabled() -> None:
    with pytest.raises(DomainError) as error:
        _require_available_signup_mode("COEXISTENCE")
    assert error.value.code == "whatsapp_coexistence_not_ready"


def test_unknown_modes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SignupStartRequest(mode="automatic")
