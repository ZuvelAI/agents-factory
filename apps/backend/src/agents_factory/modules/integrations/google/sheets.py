from __future__ import annotations

from typing import ClassVar, Self
from urllib.parse import quote

from pydantic import (
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from agents_factory.modules.integrations.contracts import ConnectorRequest
from agents_factory.modules.integrations.google.auth import SHEETS_READ, SHEETS_WRITE
from agents_factory.modules.integrations.google.base import (
    GoogleConnector,
    GoogleFailure,
    InputModel,
    ResourceId,
    manifest,
    response_string,
)


Cell = StrictStr | StrictInt | StrictFloat | StrictBool


class SheetsResource(InputModel):
    spreadsheet_id: ResourceId
    tab: str = Field(min_length=1, max_length=100, pattern=r"^[^\r\n]+$")
    # Ordered full header row and explicit domain-field -> provider-header mapping.
    headers: tuple[str, ...] = Field(min_length=1, max_length=26)
    fields: dict[str, str] = Field(min_length=1, max_length=26)
    max_rows: int = Field(default=10000, ge=2, le=100000)

    @model_validator(mode="after")
    def valid_mapping(self) -> Self:
        if (
            len(set(self.headers)) != len(self.headers)
            or any(not value.strip() for value in self.headers)
            or not set(self.fields.values()).issubset(self.headers)
            or len(set(self.fields.values())) != len(self.fields)
        ):
            raise ValueError("invalid Sheets field mapping")
        return self


class ReadRows(InputModel):
    start_row: int = Field(default=2, ge=2)
    limit: int = Field(default=100, ge=1, le=500)


class AppendRow(InputModel):
    values: dict[str, Cell] = Field(min_length=1, max_length=26)


class UpdateRow(AppendRow):
    row_number: int = Field(ge=2)
    expected: dict[str, Cell] = Field(min_length=1, max_length=26)


class GoogleSheetsConnector(GoogleConnector[SheetsResource]):
    manifest = manifest(
        "google_sheets",
        "Google Sheets",
        ("sheets.read_rows", "sheets.append_row", "sheets.update_row"),
        "sheets.GoogleSheetsConnector",
    )
    operation_scopes: ClassVar[dict[str, frozenset[str]]] = {
        "sheets.read_rows": frozenset({SHEETS_READ, SHEETS_WRITE}),
        "sheets.append_row": frozenset({SHEETS_WRITE}),
        "sheets.update_row": frozenset({SHEETS_WRITE}),
    }
    write_operations = frozenset({"sheets.append_row", "sheets.update_row"})

    def _url(self, start: int, end: int) -> str:
        if end > self.resource.max_rows:
            raise GoogleFailure("resource_not_allowed")
        tab = "'" + self.resource.tab.replace("'", "''") + "'"
        cell_range = f"{tab}!A{start}:{chr(64 + len(self.resource.headers))}{end}"
        return (
            "https://sheets.googleapis.com/v4/spreadsheets/"
            + quote(self.resource.spreadsheet_id, safe="")
            + "/values/"
            + quote(cell_range, safe="")
        )

    async def _read(self, start: int, end: int) -> list[list[Cell]]:
        payload = await self.http.json(
            "GET",
            self._url(start, end),
            access=self.access,
            params={"valueRenderOption": "UNFORMATTED_VALUE"},
        )
        values = payload.get("values", [])
        if not isinstance(values, list) or len(values) > end - start + 1:
            raise GoogleFailure("invalid_response")
        rows: list[list[Cell]] = []
        for row in values:
            if (
                not isinstance(row, list)
                or len(row) > len(self.resource.headers)
                or any(type(cell) not in {str, int, float, bool} for cell in row)
            ):
                raise GoogleFailure("invalid_response")
            rows.append(row)
        return rows

    def _mapped(self, row: list[Cell]) -> dict[str, Cell]:
        padded = row + [""] * (len(self.resource.headers) - len(row))
        return {
            field: padded[self.resource.headers.index(header)]
            for field, header in self.resource.fields.items()
        }

    def _values(self, values: dict[str, Cell]) -> dict[int, Cell]:
        if set(values) - self.resource.fields.keys() or any(
            isinstance(value, str) and len(value) > 50000 for value in values.values()
        ):
            raise GoogleFailure("invalid_arguments")
        return {
            self.resource.headers.index(self.resource.fields[key]): value
            for key, value in values.items()
        }

    async def _execute(self, request: ConnectorRequest) -> dict[str, object]:
        # Fail closed on moved/renamed/duplicate headers before reads AND writes.
        if await self._read(1, 1) != [list(self.resource.headers)]:
            raise GoogleFailure("header_mapping_mismatch")
        if request.operation == "sheets.read_rows":
            args = ReadRows.model_validate(request.arguments)
            end = min(args.start_row + args.limit - 1, self.resource.max_rows)
            if args.start_row > end:
                raise GoogleFailure("resource_not_allowed")
            rows = await self._read(args.start_row, end)
            return {
                "rows": [
                    {"row_number": args.start_row + index, "values": self._mapped(row)}
                    for index, row in enumerate(rows)
                ],
                "next_row": end + 1
                if len(rows) == args.limit and end < self.resource.max_rows
                else None,
            }
        if request.operation == "sheets.append_row":
            append = AppendRow.model_validate(request.arguments)
            row: list[Cell] = [""] * len(self.resource.headers)
            for index, value in self._values(append.values).items():
                row[index] = value
            payload = await self.http.json(
                "POST",
                self._url(1, self.resource.max_rows) + ":append",
                access=self.access,
                params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                body={"values": [row]},
                write=True,
            )
            updates = payload.get("updates")
            if not isinstance(updates, dict) or updates.get("updatedRows") != 1:
                raise GoogleFailure("invalid_response", uncertain=True)
            return {
                "updated_range": response_string(updates, "updatedRange", write=True)
            }
        update = UpdateRow.model_validate(request.arguments)
        changes = self._values(update.values)
        self._values(update.expected)
        rows = await self._read(update.row_number, update.row_number)
        if len(rows) != 1 or self._mapped(rows[0]) != update.expected:
            raise GoogleFailure("stale_version")
        # Write only target cells (preserve other cells/formulas). No atomic CAS.
        # Task 25 supplies serialization/reconciliation; never claim DB-grade CAS.
        tab = "'" + self.resource.tab.replace("'", "''") + "'"
        data = [
            {
                "range": f"{tab}!{chr(65 + index)}{update.row_number}",
                "values": [[value]],
            }
            for index, value in changes.items()
        ]
        root = (
            "https://sheets.googleapis.com/v4/spreadsheets/"
            + quote(self.resource.spreadsheet_id, safe="")
            + "/values:batchUpdate"
        )
        payload = await self.http.json(
            "POST",
            root,
            access=self.access,
            body={"valueInputOption": "RAW", "data": data},
            write=True,
        )
        if payload.get("totalUpdatedCells") != len(changes):
            raise GoogleFailure("invalid_response", uncertain=True)
        return {"row_number": update.row_number, "updated_fields": list(update.values)}
