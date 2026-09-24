import { saveOnboardingStep } from "../../app/actions";
import type { OnboardingStep } from "../../lib/onboarding";
import { UiIcon } from "../ui-icon";

type Data = Record<string, unknown>;

export function StepForm({
  tenantId,
  revision,
  step,
}: {
  tenantId: string;
  revision: number;
  step: OnboardingStep;
}) {
  if (["whatsapp", "test", "quality-gate", "production"].includes(step.key)) {
    return <ReadOnlyStep tenantId={tenantId} step={step} />;
  }

  return (
    <form action={saveOnboardingStep} className="onboarding-form">
      <input type="hidden" name="tenantId" value={tenantId} />
      <input type="hidden" name="step" value={step.key} />
      <input type="hidden" name="expectedRevision" value={revision} />
      <div className="form-heading">
        <span className="section-icon">
          <UiIcon name={step.key === "company" ? "tenants" : "settings"} />
        </span>
        <div>
          <h2>
            {step.key === "company"
              ? "Información del negocio"
              : `Configuración · ${step.title}`}
          </h2>
          <p>
            Completa los datos de este paso. Los campos con * son obligatorios.
          </p>
        </div>
        <span className="draft-label">BORRADOR</span>
      </div>
      {stepFields(step.key, step.data)}
      <div className="form-actions">
        <span>
          <UiIcon name="save" size={15} /> Tu avance se conserva al guardar.
        </span>
        <button type="submit">
          <UiIcon name="check" size={17} /> Guardar este paso
        </button>
      </div>
    </form>
  );
}

function stepFields(key: OnboardingStep["key"], data: Data) {
  switch (key) {
    case "company":
      return (
        <>
          <div className="field-grid">
            <Field
              label="Nombre legal"
              name="legal_name"
              data={data}
              required
            />
            <Field
              label="Nombre comercial"
              name="commercial_name"
              data={data}
              required
            />
            <Field label="País" name="country" data={data} required />
            <Field label="Ciudad" name="city" data={data} required />
            <Field label="Industria" name="industry" data={data} required />
            <Field label="Zona horaria" name="timezone" data={data} required />
            <SelectField
              label="Idioma principal"
              name="primary_locale"
              data={data}
              options={[
                ["es-CO", "Español (Colombia)"],
                ["en-US", "Inglés (Estados Unidos)"],
              ]}
            />
            <Field
              label="Volumen mensual estimado de WhatsApp"
              name="whatsapp_volume"
              data={data}
              placeholder="unknown"
            />
          </div>
          <TextArea
            label="Descripción del negocio"
            name="business_description"
            data={data}
            required
          />
          <Field
            label="Horario de atención"
            name="service_hours"
            data={data}
            required
          />
          <div className="field-grid">
            <Field
              label="Responsable del negocio"
              name="responsible_person"
              data={data}
              required
            />
            <Field
              label="Responsable de privacidad"
              name="privacy_contact"
              data={data}
              required
            />
            <Field
              label="Responsable de incidentes"
              name="incident_contact"
              data={data}
              required
            />
          </div>
        </>
      );
    case "agent":
      return (
        <>
          <div className="field-grid">
            <Field
              label="Nombre del agente (opcional)"
              name="agent_name"
              data={data}
            />
            <SelectField
              label="Estilo de saludo"
              name="greeting_style"
              data={data}
              options={[
                ["BRAND_ONLY", "Solo la marca"],
                ["NAMED", "Agente con nombre"],
              ]}
            />
            <SelectField
              label="Tono"
              name="tone"
              data={data}
              options={[
                ["PROFESSIONAL_WARM", "Profesional y cálido"],
                ["PROFESSIONAL_DIRECT", "Profesional y directo"],
                ["FRIENDLY", "Cercano"],
              ]}
            />
            <SelectField
              label="Tratamiento"
              name="formality"
              data={data}
              options={[
                ["USTED", "Usted"],
                ["TU", "Tú"],
              ]}
            />
          </div>
          <Field label="Saludo" name="greeting" data={data} required />
          <TextArea
            label="Instrucciones y alcance empresarial"
            name="instructions"
            data={data}
            required
          />
          <TextArea
            label="Vocabulario de marca (opcional)"
            name="brand_vocabulary"
            data={data}
          />
          <Checkboxes
            legend="Idiomas permitidos en v1"
            name="supported_languages"
            data={data}
            options={[
              ["es-CO", "Español"],
              ["en-US", "Inglés"],
            ]}
          />
        </>
      );
    case "capabilities":
      return (
        <>
          <Checkboxes
            legend="Casos de uso del cliente"
            name="use_cases"
            data={data}
            options={[
              ["company_information", "Información de empresa"],
              ["products_services", "Productos y servicios"],
              ["appointments", "Citas"],
              ["orders", "Pedidos"],
              ["returns_claims", "Devoluciones y reclamos"],
            ]}
          />
          <Checkboxes
            legend="Capability Packs requeridos"
            name="selected_capabilities"
            data={data}
            options={[
              ["appointments", "Appointments"],
              ["orders", "Orders"],
              ["returns_claims", "Returns & Claims"],
            ]}
          />
          <SelectField
            label="Clasificación general"
            name="onboarding_classification"
            data={data}
            options={classificationOptions}
          />
          <TextArea
            label="Necesidad no soportada (opcional)"
            name="unsupported_requirement"
            data={{
              unsupported_requirement: firstUnsupportedDescription(data),
            }}
          />
          <SelectField
            label="Clasificación de esa necesidad"
            name="unsupported_classification"
            data={{
              unsupported_classification: firstUnsupportedClassification(data),
            }}
            options={classificationOptions}
          />
        </>
      );
    case "integrations":
      return (
        <>
          <RadioBoolean
            legend="¿Necesita conectar sistemas empresariales además de WhatsApp?"
            name="business_systems_required"
            data={data}
          />
          <Checkboxes
            legend="Conectores requeridos"
            name="required_connectors"
            data={data}
            options={[
              ["google_workspace", "Google Workspace"],
              ["google_sheets", "Google Sheets"],
              ["woocommerce", "WooCommerce"],
            ]}
          />
          <TextArea
            label="Sistemas, campos y permisos necesarios"
            name="connection_notes"
            data={data}
          />
        </>
      );
    case "knowledge":
      return (
        <>
          <div className="field-grid">
            <Field
              label="Nombre de la fuente"
              name="source_name"
              data={data}
              required
            />
            <SelectField
              label="Tipo de fuente"
              name="source_type"
              data={data}
              options={[
                ["PDF", "PDF"],
                ["WEBSITE", "Sitio web"],
                ["INTERNAL_TEXT", "Texto interno"],
              ]}
            />
            <SelectField
              label="Autoridad"
              name="authority"
              data={data}
              options={[
                ["OFFICIAL", "Oficial"],
                ["OPERATIONAL", "Operativa"],
                ["REFERENCE", "Referencia"],
              ]}
            />
            <Field
              label="Conflictos críticos pendientes"
              name="critical_conflicts"
              data={data}
              type="number"
            />
          </div>
          <Field
            label="Archivo, URL o referencia"
            name="source_reference"
            data={data}
            required
          />
          <TextArea
            label="Contenido o resumen aprobado"
            name="approved_summary"
            data={data}
            required
          />
          <label className="checkbox-option">
            <input
              type="checkbox"
              name="review_confirmed"
              value="true"
              defaultChecked={Boolean(data.review_confirmed)}
            />
            Confirmo que esta fuente fue revisada y aprobada
          </label>
        </>
      );
    case "policies-identity":
      return (
        <>
          <div className="field-grid">
            <SelectField
              label="Respuesta sobre precios"
              name="pricing_response"
              data={data}
              emptyLabel="Seleccionar"
              options={[
                ["QUOTE_REQUIRED", "Requiere cotización"],
                ["APPROVED_PRICES_ONLY", "Solo precios aprobados"],
              ]}
            />
            <SelectField
              label="Política de privacidad"
              name="privacy_policy_status"
              data={data}
              emptyLabel="Seleccionar"
              options={[
                ["NOT_DEFINED", "Aún no definida"],
                ["DRAFT", "Borrador"],
                ["APPROVED", "Aprobada"],
              ]}
            />
            <SelectField
              label="Método de identidad del cliente"
              name="customer_identity_method"
              data={data}
              emptyLabel="Seleccionar"
              options={[
                ["NONE", "No requerido para consultas"],
                ["WHATSAPP_NUMBER", "Número de WhatsApp"],
                ["ORDER_DATA", "Datos del pedido"],
                ["ONE_TIME_CODE", "Código de un solo uso"],
              ]}
            />
          </div>
          <TextArea
            label="Notas de políticas e identidad"
            name="policy_notes"
            data={data}
          />
        </>
      );
    case "human-operations":
      return (
        <>
          <RadioBoolean
            legend="¿Se habilitará Live Human Handoff?"
            name="handoff_enabled"
            data={data}
          />
          <div className="field-grid">
            <SelectField
              label="Superficie de respuesta humana"
              name="response_surface"
              data={data}
              options={[
                ["NONE", "Ninguna"],
                ["WHATSAPP_COEXISTENCE", "WhatsApp Coexistence"],
                ["EXTERNAL_HELPDESK", "Bandeja externa compatible"],
              ]}
            />
            <SelectField
              label="Mientras espera al humano"
              name="awaiting_human_policy"
              data={data}
              options={[
                ["SILENT", "Silencio"],
                ["ACKNOWLEDGE", "Confirmar la espera"],
              ]}
            />
          </div>
          <Field
            label="Horario de atención humana"
            name="support_hours"
            data={data}
          />
        </>
      );
    case "approval-routes":
      return (
        <>
          <RadioBoolean
            legend="¿El agente realizará acciones de alto riesgo?"
            name="high_risk_actions_expected"
            data={data}
          />
          <TextArea
            label="Correos de aprobadores (uno por línea)"
            name="approver_emails"
            data={{
              approver_emails: stringList(data.approver_emails).join("\n"),
            }}
          />
          <TextArea
            label="Acciones y responsables"
            name="route_notes"
            data={data}
          />
          <p className="field-help">
            Estrategia v1: la primera aprobación o rechazo válido cierra la
            solicitud.
          </p>
        </>
      );
    default:
      return null;
  }
}

function ReadOnlyStep({
  tenantId,
  step,
}: {
  tenantId: string;
  step: OnboardingStep;
}) {
  if (step.key === "whatsapp") {
    return (
      <div className="read-only-step">
        <p>La conexión se administra en la pantalla segura de WhatsApp.</p>
        <a className="button-link" href={`/tenants/${tenantId}/whatsapp`}>
          Abrir configuración de WhatsApp
        </a>
      </div>
    );
  }
  return (
    <div className="read-only-step">
      <p>
        Este estado se obtiene automáticamente de evidencia real. No puede
        marcarse como completo manualmente.
      </p>
    </div>
  );
}

function Field({
  label,
  name,
  data,
  required = false,
  placeholder,
  type = "text",
}: {
  label: string;
  name: string;
  data: Data;
  required?: boolean;
  placeholder?: string;
  type?: "text" | "number";
}) {
  return (
    <label className="form-field">
      <span>
        {label}
        {required ? <span className="required-mark"> *</span> : null}
      </span>
      <input
        type={type}
        name={name}
        defaultValue={scalar(data[name])}
        required={required}
        placeholder={placeholder}
        min={type === "number" ? 0 : undefined}
      />
    </label>
  );
}

function TextArea({
  label,
  name,
  data,
  required = false,
}: {
  label: string;
  name: string;
  data: Data;
  required?: boolean;
}) {
  return (
    <label className="form-field form-field-wide">
      <span>
        {label}
        {required ? <span className="required-mark"> *</span> : null}
      </span>
      <textarea
        name={name}
        defaultValue={scalar(data[name])}
        required={required}
      />
    </label>
  );
}

function SelectField({
  label,
  name,
  data,
  options,
  emptyLabel,
}: {
  label: string;
  name: string;
  data: Data;
  options: readonly (readonly [string, string])[];
  emptyLabel?: string;
}) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <select name={name} defaultValue={scalar(data[name])}>
        {emptyLabel ? <option value="">{emptyLabel}</option> : null}
        {options.map(([value, text]) => (
          <option value={value} key={value}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

function Checkboxes({
  legend,
  name,
  data,
  options,
}: {
  legend: string;
  name: string;
  data: Data;
  options: readonly (readonly [string, string])[];
}) {
  const selected = new Set(stringList(data[name]));
  return (
    <fieldset className="checkbox-group">
      <legend>{legend}</legend>
      {options.map(([value, label]) => (
        <label className="checkbox-option" key={value}>
          <input
            type="checkbox"
            name={name}
            value={value}
            defaultChecked={selected.has(value)}
          />
          {label}
        </label>
      ))}
    </fieldset>
  );
}

function RadioBoolean({
  legend,
  name,
  data,
}: {
  legend: string;
  name: string;
  data: Data;
}) {
  const selected = data[name];
  return (
    <fieldset className="checkbox-group">
      <legend>{legend}</legend>
      <label className="checkbox-option">
        <input
          type="radio"
          name={name}
          value="false"
          defaultChecked={selected === false}
          required
        />
        No
      </label>
      <label className="checkbox-option">
        <input
          type="radio"
          name={name}
          value="true"
          defaultChecked={selected === true}
          required
        />
        Sí
      </label>
    </fieldset>
  );
}

const classificationOptions = [
  ["STANDARD", "Standard"],
  ["CUSTOM_CONNECTOR", "Custom Connector"],
  ["CUSTOM_WORKFLOW", "Custom Workflow"],
  ["NEW_CAPABILITY", "New Capability"],
] as const;

function scalar(value: unknown): string | number {
  return typeof value === "string" || typeof value === "number" ? value : "";
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function firstUnsupportedDescription(data: Data): string {
  const first = Array.isArray(data.unsupported_requirements)
    ? data.unsupported_requirements[0]
    : null;
  if (!first || typeof first !== "object") return "";
  const description = (first as Record<string, unknown>).description;
  return typeof description === "string" ? description : "";
}

function firstUnsupportedClassification(data: Data): string {
  const first = Array.isArray(data.unsupported_requirements)
    ? data.unsupported_requirements[0]
    : null;
  if (!first || typeof first !== "object") return "STANDARD";
  const classification = (first as Record<string, unknown>).classification;
  return typeof classification === "string" ? classification : "STANDARD";
}
