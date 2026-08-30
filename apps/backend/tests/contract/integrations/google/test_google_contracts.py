from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from agents_factory.modules.integrations.contracts import ConnectorRequest
from agents_factory.modules.integrations.google.auth import (
    CALENDAR_BUSY,
    CALENDAR_READ,
    CALENDAR_WRITE,
    DRIVE_FILE,
    GMAIL_SEND,
    SHEETS_WRITE,
    GoogleClientConfiguration,
    GoogleOAuthProvider,
    configured_google_providers,
    decode_credential,
)
from agents_factory.modules.integrations.google.base import (
    GoogleBinding,
    GoogleFailure,
    GoogleHTTP,
)
from agents_factory.modules.integrations.google.calendar import (
    CalendarResource,
    GoogleCalendarConnector,
)
from agents_factory.modules.integrations.google.drive import (
    DriveResource,
    GoogleDriveConnector,
)
from agents_factory.modules.integrations.google.factory import GOOGLE_MANIFESTS
from agents_factory.modules.integrations.google.gmail import (
    GmailConnector,
    GmailResource,
)
from agents_factory.modules.integrations.google.sheets import (
    GoogleSheetsConnector,
    SheetsResource,
)
from agents_factory.modules.integrations.oauth import ProviderFailure
from agents_factory.modules.integrations.registry import V1_CONNECTOR_CATALOG
from agents_factory.modules.secrets.redaction import ResolvedSecret


FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/provider_shapes.json").read_text()
)
WINDOW = {
    "start": "2026-09-01T14:00:00Z",
    "end": "2026-09-01T14:30:00Z",
    "timezone": "America/Bogota",
}
NOTICE = {
    "recipient": "approver@example.test",
    "subject": "Approval requested",
    "text": "Review case-1 in the secure console.",
}


def credential(scopes: tuple[str, ...], *, expired: bool = False) -> ResolvedSecret:
    return ResolvedSecret(
        json.dumps(
            {
                "access_token": "fixture-access",
                "refresh_token": "fixture-refresh",
                "scopes": scopes,
                "expires_at": (
                    datetime.now(UTC) + timedelta(hours=-1 if expired else 1)
                ).isoformat(),
            }
        ).encode()
    )


def binding(operations: tuple[str, ...]) -> GoogleBinding:
    return GoogleBinding(uuid4(), uuid4(), frozenset(operations))


def request(
    bound: GoogleBinding,
    operation: str,
    args: dict[str, object],
    *,
    key: str | None = "action-fixture",
) -> ConnectorRequest:
    return ConnectorRequest(
        tenant_id=bound.tenant_id,
        binding_id=bound.binding_id,
        operation=operation,
        arguments=args,
        idempotency_key=key,
    )


def http(handler: Callable[[httpx.Request], httpx.Response]) -> GoogleHTTP:
    return GoogleHTTP(httpx.MockTransport(handler))


async def test_oauth_pkce_exact_scopes_refresh_revocation_and_secret_free_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path.endswith("tokeninfo"):
            assert (
                req.method == "POST"
                and req.url.params["access_token"] == "fixture-access"
            )
            return httpx.Response(
                200,
                json={
                    "scope": GMAIL_SEND,
                    "issued_to": "gmail-client",
                    "expires_in": 3600,
                },
            )
        if req.url.path.endswith("revoke"):
            assert parse_qs(req.content.decode())["token"] == ["fixture-refresh"]
            assert not req.url.query
            return httpx.Response(200)
        form = parse_qs(req.content.decode())
        payload: dict[str, object] = {
            "access_token": "fixture-access",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        if form["grant_type"] == ["authorization_code"]:
            assert form["code_verifier"] == ["fixture-pkce"]
            payload.update({"scope": GMAIL_SEND, "refresh_token": "fixture-refresh"})
        else:
            assert form["refresh_token"] == ["fixture-refresh"]
        return httpx.Response(200, json=payload)

    configuration = GoogleClientConfiguration.model_validate(
        {
            "client_id": "gmail-client",
            "client_secret": "fixture-client-credential",
            "redirect_uri": "https://control.example.test/callback",
        }
    )
    provider = GoogleOAuthProvider(
        product="gmail", configuration=configuration, http=http(handler)
    )
    url = provider.oauth.authorize_url(
        state="state", code_challenge="challenge", scopes=(GMAIL_SEND,)
    )
    params = parse_qs(url.split("?", 1)[1])
    assert params["scope"] == [GMAIL_SEND] and params["code_challenge_method"] == [
        "S256"
    ]
    assert (
        params["access_type"] == ["offline"] and "include_granted_scopes" not in params
    )
    with caplog.at_level(logging.DEBUG):
        grant = await provider.exchange(
            code=ResolvedSecret(b"fixture-code"),
            verifier=ResolvedSecret(b"fixture-pkce"),
        )
        refreshed = await provider.refresh(grant.credential)
        assert (
            decode_credential(refreshed.credential).refresh.reveal()
            == b"fixture-refresh"
        )
        assert refreshed.granted_scopes == (GMAIL_SEND,)
        await provider.check_health(refreshed.credential)
        await provider.revoke(refreshed.credential)
    assert len(calls) == 4
    for sensitive in (
        "fixture-access",
        "fixture-refresh",
        "fixture-client-credential",
        "fixture-pkce",
        "fixture-code",
    ):
        assert sensitive not in caplog.text
    assert "fixture-client-credential" not in repr(configuration)
    with pytest.raises(ProviderFailure, match="authorization_revoked"):
        await provider.check_health(credential((GMAIL_SEND,), expired=True))
    bad_http = http(
        lambda req: httpx.Response(
            200,
            json={
                "access_token": "fixture-access",
                "refresh_token": "fixture-refresh",
                "expires_in": 3600,
                "scope": GMAIL_SEND + " " + DRIVE_FILE,
            },
        )
    )
    broad = GoogleOAuthProvider(
        product="gmail", configuration=configuration, http=bad_http
    )
    with pytest.raises(ProviderFailure, match="permission_denied"):
        await broad.exchange(
            code=ResolvedSecret(b"fixture-code"),
            verifier=ResolvedSecret(b"fixture-pkce"),
        )


async def test_calendar_all_declared_operations_pagination_timezone_and_reconciliation() -> (
    None
):
    bound = binding(GoogleCalendarConnector.manifest.supported_operations)
    posted: dict[str, object] = {}
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path.endswith("freeBusy"):
            return httpx.Response(200, json=FIXTURES["freebusy"])
        if req.method == "POST":
            body = json.loads(req.content)
            assert body["start"] == {
                "dateTime": "2026-09-01T09:00:00-05:00",
                "timeZone": "America/Bogota",
            }
            if posted:
                return httpx.Response(409, json={"error": {}})
            posted.update({**body, "etag": '"v1"'})
            return httpx.Response(200, json=posted)
        if req.method == "PATCH":
            assert req.headers["If-Match"] == '"v1"'
            return httpx.Response(200, json={**FIXTURES["event"], "etag": '"v2"'})
        if req.url.path.endswith("/events"):
            if "pageToken" not in req.url.params:
                return httpx.Response(
                    200,
                    json={
                        "items": [FIXTURES["event"]],
                        "nextPageToken": "fixture-page-2",
                    },
                )
            assert req.url.params["pageToken"] == "fixture-page-2"
            return httpx.Response(200, json={"items": []})
        if posted and req.url.path.endswith(str(posted["id"])):
            return httpx.Response(200, json=posted)
        return httpx.Response(200, json=FIXTURES["event"])

    adapter = GoogleCalendarConnector(
        binding=bound,
        resource=CalendarResource(calendar_id="primary"),
        credential=credential((CALENDAR_BUSY, CALENDAR_WRITE)),
        http=http(handler),
    )
    assert (
        await adapter.execute(request(bound, "calendar.check_availability", WINDOW))
    ).data["busy"]
    assert (
        len(
            (
                await adapter.execute(request(bound, "calendar.list_events", WINDOW))
            ).data["events"]
        )
        == 1
    )
    assert (
        await adapter.execute(
            request(bound, "calendar.get_event", {"event_id": "eventfixture01"})
        )
    ).data["event_id"] == "eventfixture01"
    create = request(
        bound, "calendar.create_event", {**WINDOW, "summary": "Fixture appointment"}
    )
    created = await adapter.execute(create)
    assert created.status == "SUCCEEDED" and len(created.data["event_id"]) == 64
    assert (await adapter.execute(create)).data == created.data
    assert (
        await adapter.execute(
            request(
                bound,
                "calendar.reschedule_event",
                {**WINDOW, "event_id": "eventfixture01", "etag": '"v1"'},
            )
        )
    ).data["etag"] == '"v2"'
    before = len(calls)
    bad = await adapter.execute(
        request(
            bound,
            "calendar.create_event",
            {**WINDOW, "start": "2026-09-01T14:00:00", "summary": "No offset"},
        )
    )
    assert bad.error_code == "invalid_arguments" and len(calls) == before
    unavailable = GoogleCalendarConnector(
        binding=bound,
        resource=CalendarResource(calendar_id="primary"),
        credential=credential((CALENDAR_BUSY,)),
        http=http(
            lambda req: httpx.Response(
                200,
                json={"calendars": {"primary": {"errors": [{"reason": "notFound"}]}}},
            )
        ),
    )
    assert (
        await unavailable.execute(request(bound, "calendar.check_availability", WINDOW))
    ).error_code == "availability_unknown"


async def test_gmail_notice_only_approved_recipient_and_no_implicit_retries() -> None:
    bound = binding(GmailConnector.manifest.supported_operations)
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        message = message_from_bytes(
            base64.urlsafe_b64decode(json.loads(req.content)["raw"])
        )
        assert (
            message["To"] == NOTICE["recipient"]
            and message["From"] == "ops@example.test"
        )
        assert message["Subject"] == NOTICE["subject"] and message["Message-ID"]
        assert req.url.path == "/gmail/v1/users/me/messages/send"
        return httpx.Response(200, json=FIXTURES["message"])

    resource = GmailResource(
        sender="ops@example.test",
        approval_recipients=frozenset({"approver@example.test"}),
    )
    adapter = GmailConnector(
        binding=bound,
        resource=resource,
        credential=credential((GMAIL_SEND,)),
        http=http(handler),
    )
    assert (
        await adapter.execute(request(bound, "gmail.send_approval_notice", NOTICE))
    ).data == {"message_id": "mailfixture01"}
    assert (
        await adapter.execute(
            request(
                bound,
                "gmail.send_approval_notice",
                {**NOTICE, "recipient": "other@example.test"},
            )
        )
    ).error_code == "resource_not_allowed"
    assert len(calls) == 1

    def timeout(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        raise httpx.ReadTimeout("sensitive provider diagnostic")

    adapter.http = http(timeout)
    result = await adapter.execute(request(bound, "gmail.send_approval_notice", NOTICE))
    assert result.status == "UNCERTAIN" and len(calls) == 2
    assert "sensitive" not in result.model_dump_json()


async def test_drive_private_evidence_scoped_reads_exports_mime_and_size_limits() -> (
    None
):
    bound = binding(GoogleDriveConnector.manifest.supported_operations)
    metadata = dict(FIXTURES["file"])
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.method == "POST":
            assert req.url.params["uploadType"] == "multipart"
            assert b'"parents": ["folderfixture01"]' in req.content
            assert b"evidence" in req.content and b"permissions" not in req.content
            return httpx.Response(200, json=FIXTURES["file"])
        if req.url.params.get("alt") == "media" or req.url.path.endswith("export"):
            return httpx.Response(200, content=b"evidence")
        return httpx.Response(200, json=metadata)

    resource = DriveResource(
        evidence_folder_id="folderfixture01",
        readable_file_ids=frozenset({"filefixture01"}),
        max_bytes=8,
    )
    adapter = GoogleDriveConnector(
        binding=bound,
        resource=resource,
        credential=credential((DRIVE_FILE,)),
        http=http(handler),
    )
    read = request(bound, "drive.read_file", {"file_id": "filefixture01"})
    assert (
        base64.b64decode((await adapter.execute(read)).data["content_base64"])
        == b"evidence"
    )
    upload = {
        "name": "evidence.txt",
        "mime_type": "text/plain",
        "content_base64": base64.b64encode(b"evidence").decode(),
    }
    assert (await adapter.execute(request(bound, "drive.store_evidence", upload))).data[
        "file_id"
    ] == "filefixture01"
    assert (
        await adapter.execute(
            request(bound, "drive.store_evidence", {**upload, "mime_type": "text/html"})
        )
    ).error_code == "mime_not_allowed"
    assert (
        await adapter.execute(
            request(
                bound,
                "drive.store_evidence",
                {**upload, "content_base64": base64.b64encode(b"too large").decode()},
            )
        )
    ).error_code == "file_too_large"
    before = len(calls)
    assert (
        await adapter.execute(request(bound, "drive.read_file", {"file_id": "other"}))
    ).error_code == "resource_not_allowed"
    assert len(calls) == before
    metadata["size"] = "9"
    assert (await adapter.execute(read)).error_code == "file_too_large"
    metadata.update({"size": "8", "mimeType": "application/vnd.google-apps.document"})
    assert (await adapter.execute(read)).data["mime_type"] == "text/plain"
    assert calls[-1].url.params["mimeType"] == "text/plain"
    metadata["mimeType"] = "application/x-executable"
    assert (await adapter.execute(read)).error_code == "mime_not_allowed"


async def test_sheets_mapped_read_raw_append_targeted_update_and_header_drift() -> None:
    bound = binding(GoogleSheetsConnector.manifest.supported_operations)
    headers = dict(FIXTURES["headers"])
    writes: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(
                200, json=headers if "A1:C1" in req.url.path else FIXTURES["rows"]
            )
        body = json.loads(req.content)
        writes.append(body)
        if req.url.path.endswith(":append"):
            assert req.url.params["valueInputOption"] == "RAW"
            assert body["values"] == [["case-2", "=not-a-formula", ""]]
            return httpx.Response(200, json=FIXTURES["append"])
        assert body == {
            "valueInputOption": "RAW",
            "data": [{"range": "'Queue'!B2", "values": [["CLOSED"]]}],
        }
        return httpx.Response(200, json=FIXTURES["update"])

    resource = SheetsResource(
        spreadsheet_id="sheetfixture01",
        tab="Queue",
        headers=("Case ID", "Status", "Total"),
        fields={"case_id": "Case ID", "status": "Status"},
    )
    adapter = GoogleSheetsConnector(
        binding=bound,
        resource=resource,
        credential=credential((SHEETS_WRITE,)),
        http=http(handler),
    )
    result = await adapter.execute(request(bound, "sheets.read_rows", {"limit": 1}))
    assert result.data == {
        "rows": [{"row_number": 2, "values": {"case_id": "case-1", "status": "OPEN"}}],
        "next_row": 3,
    }
    assert (
        await adapter.execute(
            request(
                bound,
                "sheets.append_row",
                {"values": {"case_id": "case-2", "status": "=not-a-formula"}},
            )
        )
    ).status == "SUCCEEDED"
    update = {
        "row_number": 2,
        "values": {"status": "CLOSED"},
        "expected": {"case_id": "case-1", "status": "OPEN"},
    }
    assert (
        await adapter.execute(request(bound, "sheets.update_row", update))
    ).status == "SUCCEEDED"
    assert (
        await adapter.execute(
            request(
                bound,
                "sheets.update_row",
                {**update, "expected": {"case_id": "case-1", "status": "CLOSED"}},
            )
        )
    ).error_code == "stale_version"
    headers["values"] = [["Status", "Case ID", "Total"]]
    assert (
        await adapter.execute(
            request(bound, "sheets.append_row", {"values": {"status": "OPEN"}})
        )
    ).error_code == "header_mapping_mismatch"
    assert len(writes) == 2


async def test_tenant_binding_operation_scope_expiry_and_idempotency_gates_precede_io() -> (
    None
):
    bound = binding(GoogleCalendarConnector.manifest.supported_operations)

    def forbidden(req: httpx.Request) -> httpx.Response:
        pytest.fail("a rejected request reached Google")

    adapter = GoogleCalendarConnector(
        binding=bound,
        resource=CalendarResource(calendar_id="primary"),
        credential=credential((CALENDAR_READ,)),
        http=http(forbidden),
    )
    base = request(bound, "calendar.get_event", {"event_id": "eventfixture01"})
    assert (
        await adapter.execute(base.model_copy(update={"tenant_id": uuid4()}))
    ).error_code == "binding_mismatch"
    assert (
        await adapter.execute(base.model_copy(update={"binding_id": uuid4()}))
    ).error_code == "binding_mismatch"
    assert (
        await adapter.execute(base.model_copy(update={"operation": "contacts.read"}))
    ).error_code == "operation_not_allowed"
    assert (
        await adapter.execute(
            request(bound, "calendar.create_event", {**WINDOW, "summary": "fixture"})
        )
    ).error_code == "insufficient_scope"
    adapter = GoogleCalendarConnector(
        binding=bound,
        resource=CalendarResource(calendar_id="primary"),
        credential=credential((CALENDAR_WRITE,)),
        http=http(forbidden),
    )
    assert (
        await adapter.execute(
            request(
                bound,
                "calendar.create_event",
                {**WINDOW, "summary": "fixture"},
                key=None,
            )
        )
    ).error_code == "idempotency_key_required"
    adapter = GoogleCalendarConnector(
        binding=bound,
        resource=CalendarResource(calendar_id="primary"),
        credential=credential((CALENDAR_READ,), expired=True),
        http=http(forbidden),
    )
    assert (await adapter.execute(base)).error_code == "credentials_expired"


async def test_provider_error_mapping_bounded_transport_and_no_redirects() -> None:
    bound = binding(GoogleCalendarConnector.manifest.supported_operations)
    for status, reason, code in (
        (401, "authError", "authorization_revoked"),
        (403, "forbidden", "permission_denied"),
        (403, "rateLimitExceeded", "rate_limited"),
        (404, "notFound", "not_found"),
        (429, "", "rate_limited"),
        (503, "backendError", "provider_unavailable"),
        (412, "", "stale_version"),
    ):
        adapter = GoogleCalendarConnector(
            binding=bound,
            resource=CalendarResource(calendar_id="primary"),
            credential=credential((CALENDAR_READ,)),
            http=http(
                lambda req: httpx.Response(
                    status,
                    json={
                        "error": {
                            "message": "private diagnostic",
                            "errors": [{"reason": reason}],
                        }
                    },
                )
            ),
        )
        result = await adapter.execute(
            request(bound, "calendar.get_event", {"event_id": "fixture"})
        )
        assert result.status == "FAILED" and result.error_code == code
        assert "private diagnostic" not in result.model_dump_json()
    with pytest.raises(GoogleFailure, match="response_too_large"):
        await http(lambda req: httpx.Response(200, content=b"0123456789")).request(
            "GET", "https://www.googleapis.com/drive/v3/files/fixture", limit=5
        )
    with pytest.raises(GoogleFailure, match="provider_rejected"):
        await http(
            lambda req: httpx.Response(
                302, headers={"location": "https://untrusted.example.test"}
            )
        ).request("GET", "https://www.googleapis.com/drive/v3/files/fixture")


def test_configuration_and_catalog_have_only_implemented_scoped_products() -> None:
    assert not configured_google_providers(None).contains("gmail")
    configuration = SecretStr(
        json.dumps(
            {
                "gmail": {
                    "client_id": "gmail-client",
                    "client_secret": "fixture-client-credential",
                    "redirect_uri": "https://control.example.test/callback",
                }
            }
        )
    )
    registry = configured_google_providers(configuration)
    assert registry.get("gmail").oauth.allowed_scopes == frozenset({GMAIL_SEND})
    for invalid in (SecretStr("{bad-json"), SecretStr('{"google_contacts": {}}')):
        with pytest.raises(ValueError, match="Invalid GOOGLE_OAUTH_CLIENTS"):
            configured_google_providers(invalid)
    assert {item.stable_name for item in GOOGLE_MANIFESTS} == {
        "google_calendar",
        "gmail",
        "google_drive",
        "google_sheets",
    }
    assert sum(len(item.supported_operations) for item in GOOGLE_MANIFESTS) == 11
    for item in GOOGLE_MANIFESTS:
        assert V1_CONNECTOR_CATALOG.get(item.stable_name, item.version) == item
    assert all(
        "contacts" not in name
        for item in V1_CONNECTOR_CATALOG.list()
        for name in item.supported_operations
    )
