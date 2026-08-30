from __future__ import annotations

from collections.abc import Iterable

from agents_factory.modules.integrations.contracts import ConnectorManifest
from agents_factory.modules.integrations.google.factory import GOOGLE_MANIFESTS


class DuplicateConnectorManifest(ValueError):
    pass


class ConnectorManifestNotFound(LookupError):
    pass


class ConnectorRegistry:
    def __init__(self, manifests: Iterable[ConnectorManifest] = ()) -> None:
        self._manifests: dict[tuple[str, str], ConnectorManifest] = {}
        for manifest in manifests:
            self.register(manifest)

    def register(self, manifest: ConnectorManifest) -> None:
        key = (manifest.stable_name, manifest.version)
        if key in self._manifests:
            raise DuplicateConnectorManifest(f"duplicate connector {key}")
        self._manifests[key] = manifest

    def get(self, stable_name: str, version: str) -> ConnectorManifest:
        try:
            return self._manifests[(stable_name, version)]
        except KeyError as error:
            raise ConnectorManifestNotFound(
                f"connector {(stable_name, version)}"
            ) from error

    def list(self) -> tuple[ConnectorManifest, ...]:
        return tuple(self._manifests[key] for key in sorted(self._manifests))


def unavailable_connector(
    stable_name: str, display_name: str, note: str
) -> ConnectorManifest:
    return ConnectorManifest(
        stable_name=stable_name,
        display_name=display_name,
        version="1.0.0",
        availability="UNAVAILABLE",
        availability_note=note,
    )


PLANNED_CONNECTORS = (
    unavailable_connector(
        "generic_rest_api",
        "Generic REST API / Webhook",
        "Deferred to v1.1 Custom Onboarding Foundation.",
    ),
    unavailable_connector("microsoft_365", "Microsoft 365", "Coming later."),
    unavailable_connector("onedrive", "OneDrive", "Coming later."),
    unavailable_connector("sharepoint", "SharePoint", "Coming later."),
    unavailable_connector("hubspot", "HubSpot", "Coming later."),
    unavailable_connector("shopify", "Shopify", "Coming later."),
    unavailable_connector("crm_helpdesk", "CRM / Helpdesk", "Coming later."),
    unavailable_connector("accounting", "Accounting", "Coming later."),
    unavailable_connector("salesforce", "Salesforce", "Coming later."),
)


V1_CONNECTOR_CATALOG = ConnectorRegistry((*PLANNED_CONNECTORS, *GOOGLE_MANIFESTS))
