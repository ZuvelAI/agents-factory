import { updateAgentPresentation } from "../../app/actions";
import type { AgentEditorState } from "../../lib/tenant";
import { FormActions, FormSection } from "../forms";

export function PersonaForm({
  tenantId,
  agent,
}: {
  tenantId: string;
  agent: AgentEditorState;
}) {
  const persona = agent.editable_version.configuration.persona;
  return (
    <form action={updateAgentPresentation} className="configuration-form">
      <input type="hidden" name="tenantId" value={tenantId} />
      <input type="hidden" name="instanceId" value={agent.instance.id} />
      <input type="hidden" name="versionId" value={agent.editable_version.id} />
      <input type="hidden" name="section" value="persona" />
      <FormSection
        title="Voice and presentation"
        description="These choices shape how the agent presents the business. Platform safety rules cannot be changed here."
      >
        <div className="form-grid">
          <label>
            Agent name <span>Optional</span>
            <input
              defaultValue={persona.agent_name ?? ""}
              maxLength={80}
              name="agentName"
              placeholder="Example: Ana"
            />
          </label>
          <label>
            Tone
            <select defaultValue={persona.tone} name="tone" required>
              <option>Cercano y claro</option>
              <option>Cálido y empático</option>
              <option>Profesional y directo</option>
            </select>
          </label>
          <label>
            Formality
            <select defaultValue={persona.formality} name="formality" required>
              <option>Neutral</option>
              <option>Tú</option>
              <option>Usted</option>
            </select>
          </label>
          <label className="full-width-field">
            Brand vocabulary
            <textarea
              defaultValue={persona.brand_vocabulary.join(", ")}
              maxLength={3000}
              name="brandVocabulary"
              placeholder="Words or expressions separated by commas"
              rows={3}
            />
          </label>
          <label className="full-width-field">
            Initial greeting
            <textarea
              defaultValue={persona.greeting}
              maxLength={500}
              name="greeting"
              rows={3}
              required
            />
          </label>
        </div>
      </FormSection>
      <FormActions>
        <button type="submit">Save as new Draft</button>
      </FormActions>
    </form>
  );
}
