"""Explicit test doubles for Task 30 contracts, never production persistence."""

import asyncio
import base64
import copy
import json
import re
from contextlib import asynccontextmanager
from email import message_from_bytes
from urllib.parse import unquote
from uuid import uuid4

import httpx

from agents_factory.modules.cases.claims_contracts import ClaimCase, ClaimCaseConflict
from agents_factory.modules.integrations.contracts import ConnectorResult
from agents_factory.modules.integrations.google.auth import (
    DRIVE_FILE,
    GMAIL_SEND,
    SHEETS_WRITE,
)
from agents_factory.modules.integrations.google.base import GoogleBinding, GoogleHTTP
from agents_factory.modules.integrations.google.drive import GoogleDriveConnector
from agents_factory.modules.integrations.google.gmail import GmailConnector
from agents_factory.modules.integrations.google.sheets import GoogleSheetsConnector
from apps.backend.tests.contract.integrations.google.test_google_contracts import (
    credential,
)


class ClaimCasesFixture:
    available = True

    def __init__(self):
        self.records, self.receipts = {}, {}
        self.lock = asyncio.Lock()

    async def find_open(self, *, context, customer_ref, deduplication_key):
        return next(
            (
                case
                for case in self.records.values()
                if case.intake.tenant_id == context.tenant_id
                and case.intake.customer_ref == customer_ref
                and case.intake.deduplication_key == deduplication_key
                and case.status in {"OPEN", "AWAITING_INFORMATION", "READY_FOR_REVIEW"}
            ),
            None,
        )

    async def get(self, *, context, customer_ref, case_id):
        case = self.records.get(case_id)
        return (
            case
            if case
            and case.intake.tenant_id == context.tenant_id
            and case.intake.customer_ref == customer_ref
            else None
        )

    async def upsert(
        self,
        *,
        context,
        action_id,
        parameter_digest,
        intake,
        expected_revision,
        case_id,
    ):
        assert intake.tenant_id == context.tenant_id
        async with self.lock:
            replay = self.receipts.get((context.tenant_id, action_id))
            if replay:
                if replay[0] != parameter_digest:
                    raise ClaimCaseConflict("fixture_replay_conflict")
                return replay[1]
            current = await self.find_open(
                context=context,
                customer_ref=intake.customer_ref,
                deduplication_key=intake.deduplication_key,
            )
            if (current.revision if current else 0) != expected_revision or (
                case_id is not None and (current is None or current.case_id != case_id)
            ):
                raise ClaimCaseConflict("fixture_revision_conflict")
            unchanged = (
                current is not None
                and current.intake.content_digest == intake.content_digest
            )
            case = ClaimCase(
                case_id=current.case_id if current else uuid4(),
                intake=intake,
                revision=current.revision
                if unchanged
                else (current.revision + 1 if current else 1),
                status=intake.completeness.state,
            )
            self.records[case.case_id] = case
            self.receipts[(context.tenant_id, action_id)] = (parameter_digest, case)
            return case


class DeliveryLedgerFixture:
    available = True

    def __init__(self):
        self.records, self.locks = {}, {}

    @asynccontextmanager
    async def serialized(self, *, context, key):
        async with self.locks.setdefault((context.tenant_id, key), asyncio.Lock()):
            yield

    async def once(self, *, context, key, digest, operation, effect):
        scoped = (context.tenant_id, key)
        if scoped in self.records:
            previous_digest, result = self.records[scoped]
            if digest != previous_digest:
                return ConnectorResult(
                    operation=operation,
                    status="REJECTED",
                    error_code="fixture_payload_conflict",
                )
            return result or ConnectorResult(
                operation=operation,
                status="UNCERTAIN",
                error_code="fixture_interrupted_effect",
            )
        self.records[scoped] = (digest, None)
        result = await effect()
        assert result.operation == operation
        self.records[scoped] = (digest, result)
        return result


class GoogleClaimsFixture:
    def __init__(self, configuration):
        self.configuration = configuration
        self.rows = [list(configuration.sheets.headers)]
        self.writes = []
        self.fail_gmail = False
        self.http = GoogleHTTP(httpx.MockTransport(self.handle))

    def connectors(self, configuration, product):
        assert configuration == self.configuration
        constructor, resource, scopes, operations = {
            "google_sheets": (
                GoogleSheetsConnector,
                configuration.sheets,
                (SHEETS_WRITE,),
                ("sheets.read_rows", "sheets.append_row", "sheets.update_row"),
            ),
            "google_drive": (
                GoogleDriveConnector,
                configuration.drive,
                (DRIVE_FILE,),
                ("drive.store_evidence",),
            ),
            "gmail": (
                GmailConnector,
                configuration.gmail,
                (GMAIL_SEND,),
                ("gmail.send_approval_notice",),
            ),
        }[product]
        return constructor(
            binding=GoogleBinding(
                configuration.tenant_id, configuration.binding_id, frozenset(operations)
            ),
            resource=resource,
            credential=credential(scopes),
            http=self.http,
        )

    def handle(self, request):
        path = unquote(request.url.path)
        if request.url.host == "sheets.googleapis.com":
            if request.method == "GET":
                match = re.search(r"!A(\d+):[A-Z](\d+)$", path)
                assert match, path
                return httpx.Response(
                    200,
                    json={
                        "values": copy.deepcopy(
                            self.rows[int(match[1]) - 1 : int(match[2])]
                        )
                    },
                )
            body = json.loads(request.content)
            if path.endswith(":append"):
                assert request.url.params["valueInputOption"] == "RAW"
                self.writes.append("append")
                self.rows.extend(body["values"])
                return httpx.Response(
                    200,
                    json={
                        "updates": {
                            "updatedRows": 1,
                            "updatedRange": f"Cases!A{len(self.rows)}:K{len(self.rows)}",
                        }
                    },
                )
            assert body["valueInputOption"] == "RAW"
            self.writes.append("update")
            for entry in body["data"]:
                match = re.search(r"!([A-Z])(\d+)$", entry["range"])
                self.rows[int(match[2]) - 1][ord(match[1]) - ord("A")] = entry[
                    "values"
                ][0][0]
            return httpx.Response(200, json={"totalUpdatedCells": len(body["data"])})
        if request.url.host == "www.googleapis.com":
            assert path == "/upload/drive/v3/files"
            assert b'"parents": ["evidence-folder"]' in request.content
            assert (
                b"video/mp4" in request.content or b"application/pdf" in request.content
            )
            self.writes.append("drive")
            return httpx.Response(
                200, json={"id": f"file-{self.writes.count('drive')}"}
            )
        assert request.url.host == "gmail.googleapis.com"
        self.writes.append("gmail")
        message = message_from_bytes(
            base64.urlsafe_b64decode(json.loads(request.content)["raw"])
        )
        assert message["To"] == self.configuration.notify
        if self.fail_gmail:
            raise httpx.ReadTimeout("fixture acceptance then timeout", request=request)
        return httpx.Response(200, json={"id": f"notice-{self.writes.count('gmail')}"})
