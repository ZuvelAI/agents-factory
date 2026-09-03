import { updateTenantProfile } from "../../../../actions";
import { FormActions, FormSection } from "../../../../../components/forms";
import { callAuthenticatedBackend } from "../../../../../lib/api";
import type { Tenant } from "../../../../../lib/tenant";

export default async function TenantSettingsPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ error?: string; saved?: string }>;
}) {
  const { tenantId } = await params;
  const query = await searchParams;
  const tenant = await callAuthenticatedBackend<Tenant>(
    `/admin/tenants/${encodeURIComponent(tenantId)}`,
  );
  return (
    <section className="tenant-section">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Tenant settings</p>
        <h2>Business profile</h2>
        <p>Keep the client identity and regional defaults current.</p>
      </header>
      {query.error === "stale" ? (
        <p className="form-notice form-notice-error" role="alert">
          Another administrator updated this profile. The current values are
          shown; review them before saving again.
        </p>
      ) : query.error ? (
        <p className="form-notice form-notice-error" role="alert">
          The business profile could not be saved.
        </p>
      ) : query.saved ? (
        <p className="form-notice form-notice-success" role="status">
          Business profile saved.
        </p>
      ) : null}
      <form action={updateTenantProfile} className="configuration-form">
        <input type="hidden" name="tenantId" value={tenantId} />
        <input type="hidden" name="revision" value={tenant.revision} />
        <FormSection title="Company and region">
          <div className="form-grid">
            <label>
              Display name
              <input
                defaultValue={tenant.name}
                maxLength={200}
                name="name"
                required
              />
            </label>
            <label>
              Legal name
              <input
                defaultValue={tenant.legal_name ?? ""}
                maxLength={200}
                name="legalName"
                required
              />
            </label>
            <label>
              Industry
              <input
                defaultValue={tenant.industry ?? ""}
                maxLength={120}
                name="industry"
                required
              />
            </label>
            <label>
              Timezone
              <input
                defaultValue={tenant.timezone ?? "America/Bogota"}
                maxLength={100}
                name="timezone"
                required
              />
            </label>
            <label>
              Primary locale
              <select
                defaultValue={tenant.locale ?? "es-CO"}
                name="locale"
                required
              >
                <option value="es-CO">Spanish (Colombia)</option>
                <option value="en-US">English (United States)</option>
              </select>
            </label>
          </div>
        </FormSection>
        <FormActions>
          <button type="submit">Save profile</button>
        </FormActions>
      </form>
    </section>
  );
}
