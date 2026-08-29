from __future__ import annotations

from collections.abc import Iterable

from agents_factory.modules.capabilities.contracts import (
    CapabilityManifest,
    TenantExtensionManifest,
)


class DuplicateManifest(ValueError):
    pass


class ManifestNotFound(LookupError):
    pass


class ExtensionRegistrationError(ValueError):
    pass


class CapabilityRegistry:
    def __init__(self, manifests: Iterable[CapabilityManifest] = ()) -> None:
        self._manifests: dict[tuple[str, str], CapabilityManifest] = {}
        for manifest in manifests:
            self.register(manifest)

    def register(self, manifest: CapabilityManifest) -> None:
        key = (manifest.stable_name, manifest.version)
        if key in self._manifests:
            raise DuplicateManifest(f"duplicate capability {key}")
        self._manifests[key] = manifest

    def get(self, stable_name: str, version: str) -> CapabilityManifest:
        try:
            return self._manifests[(stable_name, version)]
        except KeyError as error:
            raise ManifestNotFound(f"capability {(stable_name, version)}") from error

    def list(self) -> tuple[CapabilityManifest, ...]:
        return tuple(self._manifests[key] for key in sorted(self._manifests))


V1_CAPABILITY_REGISTRY = CapabilityRegistry()


class TenantExtensionRegistry:
    """v1 boundary: explicit entry points only, with no shipped extensions."""

    def __init__(self, *, registered_entry_points: Iterable[str] = ()) -> None:
        self._entry_points = frozenset(registered_entry_points)
        self._manifests: dict[tuple[str, str], TenantExtensionManifest] = {}

    def register(self, manifest: TenantExtensionManifest) -> None:
        if manifest.entry_point not in self._entry_points:
            raise ExtensionRegistrationError("extension entry point is not registered")
        if manifest.enabled:
            raise ExtensionRegistrationError("Tenant Extensions are disabled in v1")
        key = (manifest.stable_name, manifest.version)
        if key in self._manifests:
            raise DuplicateManifest(f"duplicate tenant extension {key}")
        self._manifests[key] = manifest

    def list(self) -> tuple[TenantExtensionManifest, ...]:
        return tuple(self._manifests[key] for key in sorted(self._manifests))


V1_TENANT_EXTENSIONS = TenantExtensionRegistry()
