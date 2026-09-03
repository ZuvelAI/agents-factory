import { CapabilityCard } from "../../../components/configuration/capability-card";
import { callAuthenticatedBackend } from "../../../lib/api";
import type { CapabilityManifest } from "../../../lib/configuration";

export default async function CapabilitiesPage() {
  const manifests = await callAuthenticatedBackend<CapabilityManifest[]>(
    "/admin/capabilities",
  );
  const operations = new Set(
    manifests.flatMap((manifest) =>
      manifest.actions.flatMap(
        (action) => action.required_connector_operations,
      ),
    ),
  );

  return (
    <section className="narrow-page configuration-page">
      <header className="page-heading">
        <p className="eyebrow">Shared registry</p>
        <h1>Capability Packs</h1>
        <p>
          The approved v1 building blocks. Enable and configure them inside a
          tenant Draft.
        </p>
      </header>
      <div className="configuration-grid">
        {manifests.map((manifest) => (
          <CapabilityCard
            boundOperations={operations}
            editable={false}
            enabled={false}
            key={manifest.stable_name}
            manifest={manifest}
          />
        ))}
      </div>
    </section>
  );
}
