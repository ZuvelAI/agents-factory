import { updateAgentPresentation } from "../../app/actions";
import type { AgentEditorState } from "../../lib/tenant";
import { FormActions, FormSection } from "../forms";

export function LanguageForm({
  tenantId,
  agent,
}: {
  tenantId: string;
  agent: AgentEditorState;
}) {
  const language = agent.editable_version.configuration.language;
  return (
    <form action={updateAgentPresentation} className="configuration-form">
      <input type="hidden" name="tenantId" value={tenantId} />
      <input type="hidden" name="instanceId" value={agent.instance.id} />
      <input type="hidden" name="versionId" value={agent.editable_version.id} />
      <input type="hidden" name="section" value="language" />
      <FormSection
        title="Languages"
        description="Version 1 supports Spanish (Colombia) and English (United States)."
      >
        <div className="checkbox-group">
          <label>
            <input
              defaultChecked={language.supported_locales.includes("es-CO")}
              name="supportedLocales"
              type="checkbox"
              value="es-CO"
            />
            Spanish (Colombia)
          </label>
          <label>
            <input
              defaultChecked={language.supported_locales.includes("en-US")}
              name="supportedLocales"
              type="checkbox"
              value="en-US"
            />
            English (United States)
          </label>
        </div>
        <label className="select-field">
          Primary language
          <select
            defaultValue={language.default_locale}
            name="defaultLocale"
            required
          >
            <option value="es-CO">Spanish (Colombia)</option>
            <option value="en-US">English (United States)</option>
          </select>
        </label>
      </FormSection>
      <FormActions>
        <button type="submit">Save as new Draft</button>
      </FormActions>
    </form>
  );
}
