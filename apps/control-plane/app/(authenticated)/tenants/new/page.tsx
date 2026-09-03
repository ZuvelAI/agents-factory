import Link from "next/link";

import { createTenant } from "../../../actions";
import { FormActions, FormSection } from "../../../../components/forms";

export default async function NewTenantPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  return (
    <div className="narrow-page">
      <header className="page-heading">
        <p className="eyebrow">Guided client setup</p>
        <h1>Create tenant</h1>
        <p>
          Start a reusable, isolated client environment. No code or repository
          fork is created for the customer.
        </p>
      </header>
      {error ? (
        <p className="form-notice form-notice-error" role="alert">
          The tenant could not be created. Review the unique slug and required
          fields.
        </p>
      ) : null}
      <form action={createTenant} className="configuration-form">
        <FormSection
          title="Business profile"
          description="This information becomes the foundation for the client's configuration wizard."
        >
          <div className="form-grid">
            <label>
              Display name
              <input maxLength={200} name="name" required />
            </label>
            <label>
              Legal name
              <input maxLength={200} name="legalName" required />
            </label>
            <label>
              Tenant slug
              <input
                maxLength={63}
                name="slug"
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                placeholder="acme-colombia"
                required
              />
            </label>
            <label>
              Industry
              <input maxLength={120} name="industry" required />
            </label>
            <label>
              Timezone
              <input
                defaultValue="America/Bogota"
                maxLength={100}
                name="timezone"
                required
              />
            </label>
            <label>
              Primary locale
              <select defaultValue="es-CO" name="locale" required>
                <option value="es-CO">Spanish (Colombia)</option>
                <option value="en-US">English (United States)</option>
              </select>
            </label>
          </div>
        </FormSection>
        <FormActions>
          <Link className="secondary-link" href="/tenants">
            Cancel
          </Link>
          <button type="submit">Create and continue</button>
        </FormActions>
      </form>
    </div>
  );
}
