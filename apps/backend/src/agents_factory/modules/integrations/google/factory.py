from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.modules.integrations.contracts import (
    Connector,
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.integrations.google.auth import GoogleProduct
from agents_factory.modules.integrations.google.base import GoogleBinding, GoogleHTTP
from agents_factory.modules.integrations.google.calendar import (
    CalendarResource,
    GoogleCalendarConnector,
)
from agents_factory.modules.integrations.google.drive import (
    DriveResource,
    GoogleDriveConnector,
)
from agents_factory.modules.integrations.google.gmail import (
    GmailConnector,
    GmailResource,
)
from agents_factory.modules.integrations.google.sheets import (
    GoogleSheetsConnector,
    SheetsResource,
)
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.modules.secrets.redaction import ResolvedSecret


GOOGLE_MANIFESTS = (
    GoogleCalendarConnector.manifest,
    GmailConnector.manifest,
    GoogleDriveConnector.manifest,
    GoogleSheetsConnector.manifest,
)


@dataclass(frozen=True)
class ConnectedGoogleConnector:
    """Backend composition, invoked only AFTER capability/action policy gates.

    Contains connection IDs, not decrypted credentials. No arbitrary execute HTTP
    endpoint is registered. Resource config comes from trusted tenant setup.
    """

    service: IntegrationService
    context: TenantContext
    connection_id: UUID
    product: GoogleProduct
    binding: GoogleBinding
    resource: CalendarResource | GmailResource | DriveResource | SheetsResource
    http: GoogleHTTP

    def _build(self, credential: ResolvedSecret) -> Connector:
        if self.product == "google_calendar" and isinstance(
            self.resource, CalendarResource
        ):
            return GoogleCalendarConnector(
                binding=self.binding,
                resource=self.resource,
                credential=credential,
                http=self.http,
            )
        if self.product == "gmail" and isinstance(self.resource, GmailResource):
            return GmailConnector(
                binding=self.binding,
                resource=self.resource,
                credential=credential,
                http=self.http,
            )
        if self.product == "google_drive" and isinstance(self.resource, DriveResource):
            return GoogleDriveConnector(
                binding=self.binding,
                resource=self.resource,
                credential=credential,
                http=self.http,
            )
        if self.product == "google_sheets" and isinstance(
            self.resource, SheetsResource
        ):
            return GoogleSheetsConnector(
                binding=self.binding,
                resource=self.resource,
                credential=credential,
                http=self.http,
            )
        raise ValueError("Google product/resource binding mismatch")

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        return await self.service.execute_connector(
            context=self.context,
            connection_id=self.connection_id,
            connector_name=self.product,
            request=request,
            build=self._build,
        )
