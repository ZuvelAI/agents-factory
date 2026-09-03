from agents_factory.modules.observability.tracing import sanitize_payload


def test_observability_payload_removes_secrets_and_personal_content() -> None:
    payload = sanitize_payload(
        {
            "token": "secret-token",
            "otp_code": "123456",
            "authorization": "Bearer secret",
            "card_number": "4111111111111111",
            "customer_email": "person@example.test",
            "safe": {
                "status": "failed",
                "error_code": "provider_timeout",
                "provider_note": "contact person@example.test",
            },
        }
    )

    assert payload == {
        "safe": {
            "status": "failed",
            "error_code": "provider_timeout",
            "provider_note": "[REDACTED]",
        }
    }
    assert "secret-token" not in repr(payload)
