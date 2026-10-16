"use client";

import type {
  ConfigurationSection,
  JsonValue,
} from "../../lib/agent-configuration";

export type FieldDefinition = {
  key: string;
  label: string;
  max?: number;
  options?: string[];
  kind?: "text" | "multiline" | "boolean" | "list" | "number";
};
const optionLabels: Record<string, string> = {
  NAMED: "Presentarse con su nombre",
  BRAND_ONLY: "Presentarse como la marca",
  PROFESSIONAL_WARM: "Profesional y cercano",
  PROFESSIONAL_DIRECT: "Profesional y directo",
  FRIENDLY: "Amigable",
  USTED: "Usted",
  TU: "Tú",
  INTERNAL_TEXT: "Texto interno",
  WEBSITE: "Sitio web (referencia)",
  OFFICIAL: "Oficial",
  OPERATIONAL: "Operativa",
  REFERENCE: "Referencia",
  QUOTE_REQUIRED: "Requiere cotización",
  APPROVED_PRICES_ONLY: "Solo precios aprobados",
  NOT_DEFINED: "Sin definir",
  DRAFT: "Borrador",
  APPROVED: "Aprobada",
  NONE: "Ninguno",
  WHATSAPP_NUMBER: "Número de WhatsApp",
  ORDER_DATA: "Datos del pedido (requiere integración)",
  ONE_TIME_CODE: "Código de un solo uso (requiere integración)",
  WHATSAPP_COEXISTENCE: "WhatsApp en coexistencia",
  EXTERNAL_HELPDESK: "Mesa de ayuda externa (requiere integración)",
  SILENT: "Esperar en silencio",
  ACKNOWLEDGE: "Confirmar espera (requiere implementación)",
};
export function ConfigurationFields({
  prefix,
  fields,
  value,
  onChange,
}: {
  prefix: string;
  fields: FieldDefinition[];
  value: ConfigurationSection;
  onChange: (key: string, value: JsonValue) => void;
}) {
  return (
    <div className="configuration-fields">
      {fields.map((field) => {
        const id = `${prefix}-${field.key}`,
          current = value[field.key];
        return (
          <label
            key={id}
            htmlFor={id}
            className={
              field.kind === "multiline"
                ? "configuration-field-wide"
                : undefined
            }
          >
            {field.label}
            {field.kind === "boolean" ? (
              <select
                id={id}
                value={
                  current === null || current === undefined
                    ? ""
                    : String(current)
                }
                onChange={(event) =>
                  onChange(
                    field.key,
                    event.target.value === ""
                      ? null
                      : event.target.value === "true",
                  )
                }
              >
                <option value="">Sin definir</option>
                <option value="false">No</option>
                <option value="true">Sí</option>
              </select>
            ) : field.options ? (
              <select
                id={id}
                value={typeof current === "string" ? current : ""}
                onChange={(event) =>
                  onChange(field.key, event.target.value || null)
                }
              >
                <option value="">Sin definir</option>
                {field.options.map((option) => (
                  <option key={option} value={option}>
                    {optionLabels[option] ?? option}
                  </option>
                ))}
              </select>
            ) : field.kind === "multiline" || field.kind === "list" ? (
              <textarea
                id={id}
                rows={field.kind === "multiline" ? 6 : 3}
                maxLength={field.max}
                value={
                  Array.isArray(current)
                    ? current.join("\n")
                    : String(current ?? "")
                }
                onChange={(event) =>
                  onChange(
                    field.key,
                    field.kind === "list"
                      ? event.target.value.split("\n").filter(Boolean)
                      : event.target.value,
                  )
                }
              />
            ) : (
              <input
                id={id}
                type={field.kind === "number" ? "number" : "text"}
                min={field.kind === "number" ? 0 : undefined}
                maxLength={field.max}
                value={String(current ?? "")}
                onChange={(event) =>
                  onChange(
                    field.key,
                    field.kind === "number"
                      ? Number(event.target.value)
                      : event.target.value,
                  )
                }
              />
            )}
          </label>
        );
      })}
    </div>
  );
}

export const agentFields: FieldDefinition[] = [
  { key: "agent_name", label: "Nombre del agente", max: 100 },
  {
    key: "greeting_style",
    label: "Presentación",
    options: ["NAMED", "BRAND_ONLY"],
  },
  {
    key: "tone",
    label: "Tono",
    options: ["PROFESSIONAL_WARM", "PROFESSIONAL_DIRECT", "FRIENDLY"],
  },
  { key: "formality", label: "Tratamiento", options: ["USTED", "TU"] },
  { key: "greeting", label: "Saludo", kind: "multiline", max: 1000 },
  {
    key: "instructions",
    label: "Instrucciones del agente",
    kind: "multiline",
    max: 50000,
  },
  {
    key: "supported_languages",
    label: "Idiomas (es-CO o en-US, uno por línea)",
    kind: "list",
  },
  {
    key: "brand_vocabulary",
    label: "Vocabulario de marca",
    kind: "multiline",
    max: 2000,
  },
];
export const companyFields: FieldDefinition[] = [
  { key: "commercial_name", label: "Nombre comercial", max: 200 },
  { key: "legal_name", label: "Razón social", max: 200 },
  {
    key: "business_description",
    label: "Descripción de la empresa",
    kind: "multiline",
    max: 5000,
  },
  { key: "industry", label: "Sector", max: 160 },
  { key: "country", label: "País", max: 100 },
  { key: "city", label: "Ciudad", max: 100 },
  { key: "timezone", label: "Zona horaria", max: 100 },
  {
    key: "primary_locale",
    label: "Idioma principal",
    options: ["es-CO", "en-US"],
  },
  { key: "service_hours", label: "Horario de atención", max: 500 },
  { key: "responsible_person", label: "Responsable", max: 200 },
  { key: "privacy_contact", label: "Contacto de privacidad", max: 200 },
  { key: "incident_contact", label: "Contacto de incidentes", max: 200 },
];
