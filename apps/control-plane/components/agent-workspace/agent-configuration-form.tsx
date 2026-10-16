"use client";

import Link from "next/link";
import { useActionState, useEffect, useState } from "react";
import type {
  ConfigurationActionState,
  Draft,
  JsonValue,
} from "../../lib/agent-configuration";
import {
  compareCompanyProfile,
  refreshAgentCompany,
  saveAgentConfiguration,
} from "./configuration-actions";
import { ConfigurationFields, agentFields } from "./configuration-fields";
import { ConfigurationConflict } from "./configuration-conflict";

export function AgentConfigurationForm({ initial }: { initial: Draft }) {
  const [draft, setDraft] = useState(initial),
    [dirty, setDirty] = useState(false);
  const [profile, setProfile] = useState<ConfigurationActionState>({
    status: "idle",
  });
  const [state, action, pending] = useActionState(
    async (previous: ConfigurationActionState, form: FormData) => {
      const result = await saveAgentConfiguration(previous, form);
      if (result.draft) {
        setDraft(result.draft);
        setDirty(false);
      }
      return result;
    },
    { status: "idle" } as ConfigurationActionState,
  );
  const [refresh, refreshAction, refreshPending] = useActionState(
    async (previous: ConfigurationActionState, form: FormData) => {
      const result = await refreshAgentCompany(previous, form);
      if (result.draft) {
        setDraft(result.draft);
        setDirty(false);
        setProfile({ status: "idle" });
      }
      return result;
    },
    { status: "idle" } as ConfigurationActionState,
  );
  useEffect(() => {
    if (!dirty) return;
    const before = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    const navigate = (event: MouseEvent) => {
      if (
        event.target instanceof Element &&
        event.target.closest("a[href]") &&
        !window.confirm(
          "Tienes cambios sin guardar. ¿Quieres salir y descartarlos?",
        )
      )
        event.preventDefault();
    };
    window.addEventListener("beforeunload", before);
    document.addEventListener("click", navigate, true);
    return () => {
      window.removeEventListener("beforeunload", before);
      document.removeEventListener("click", navigate, true);
    };
  }, [dirty]);
  function update(section: string, key: string, value: JsonValue) {
    setDraft((current) => ({
      ...current,
      configuration: {
        ...current.configuration,
        [section]: {
          ...(current.configuration[section] as Record<string, JsonValue>),
          [key]: value,
          ...(section === "knowledge" && key !== "review_confirmed"
            ? { review_confirmed: false }
            : {}),
        },
      },
    }));
    setDirty(true);
  }
  return (
    <section className="workspace configuration-editor">
      <Link
        href={`/tenants/${draft.tenant_id}/agents/${draft.agent_instance_id}`}
      >
        ← Ficha del agente
      </Link>
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">Configuración independiente</p>
          <h1>Editar agente</h1>
          <p>
            Revisión {draft.revision} · Solo borrador. Guardar no cambia las
            respuestas de WhatsApp.
          </p>
        </div>
        <span className="workspace-tag">
          {dirty ? "Cambios sin guardar" : "Borrador"}
        </span>
      </header>
      {state.message ? <p role="status">{state.message}</p> : null}
      {state.status === "conflict" ? (
        <ConfigurationConflict
          local={draft}
          onAccept={(current) => {
            setDraft(current);
            setDirty(false);
          }}
        />
      ) : null}
      <form action={action}>
        <input type="hidden" name="tenantId" value={draft.tenant_id} />
        <input type="hidden" name="agentId" value={draft.agent_instance_id} />
        <input type="hidden" name="revision" value={draft.revision} />
        <input
          type="hidden"
          name="configuration"
          value={JSON.stringify(draft.configuration)}
        />
        <div className="workspace-sections">
          <details open>
            <summary>Identidad y comportamiento</summary>
            <label>
              Propósito
              <textarea
                rows={3}
                maxLength={2000}
                value={String(draft.configuration.purpose ?? "")}
                onChange={(event) => {
                  setDraft({
                    ...draft,
                    configuration: {
                      ...draft.configuration,
                      purpose: event.target.value,
                    },
                  });
                  setDirty(true);
                }}
              />
            </label>
            <ConfigurationFields
              prefix="agent"
              fields={agentFields}
              value={draft.configuration.agent}
              onChange={(key, value) => update("agent", key, value)}
            />
          </details>
          <details>
            <summary>Conocimiento de la empresa</summary>
            <p>
              Escribe el contenido que podrá usar el agente. Registrar una URL o
              un PDF no descarga su contenido.
            </p>
            <ConfigurationFields
              prefix="knowledge"
              value={draft.configuration.knowledge}
              onChange={(key, value) => update("knowledge", key, value)}
              fields={[
                { key: "source_name", label: "Nombre de la fuente", max: 300 },
                {
                  key: "source_type",
                  label: "Tipo de fuente",
                  options: ["INTERNAL_TEXT", "WEBSITE", "PDF"],
                },
                {
                  key: "source_reference",
                  label: "Referencia de la fuente",
                  max: 2000,
                },
                {
                  key: "authority",
                  label: "Autoridad de la fuente",
                  options: ["OFFICIAL", "OPERATIONAL", "REFERENCE"],
                },
                {
                  key: "approved_summary",
                  label: "Conocimiento empresarial",
                  kind: "multiline",
                  max: 10000,
                },
                {
                  key: "critical_conflicts",
                  label: "Conflictos críticos pendientes",
                  kind: "number",
                },
                {
                  key: "review_confirmed",
                  label: "He revisado este contenido exacto",
                  kind: "boolean",
                },
              ]}
            />
          </details>
          <details>
            <summary>Políticas y operación</summary>
            <ConfigurationFields
              prefix="policies"
              value={draft.configuration.policies_identity}
              onChange={(key, value) => update("policies_identity", key, value)}
              fields={[
                {
                  key: "pricing_response",
                  label: "Respuesta sobre precios",
                  options: ["QUOTE_REQUIRED", "APPROVED_PRICES_ONLY"],
                },
                {
                  key: "privacy_policy_status",
                  label: "Política de privacidad",
                  options: ["NOT_DEFINED", "DRAFT", "APPROVED"],
                },
                {
                  key: "customer_identity_method",
                  label: "Método de identidad",
                  options: [
                    "NONE",
                    "WHATSAPP_NUMBER",
                    "ORDER_DATA",
                    "ONE_TIME_CODE",
                  ],
                },
                {
                  key: "policy_notes",
                  label: "Notas de políticas",
                  kind: "multiline",
                  max: 5000,
                },
              ]}
            />
            <ConfigurationFields
              prefix="human"
              value={draft.configuration.human_operations}
              onChange={(key, value) => update("human_operations", key, value)}
              fields={[
                {
                  key: "handoff_enabled",
                  label:
                    "Solicitar derivación automática (requiere implementación)",
                  kind: "boolean",
                },
                {
                  key: "response_surface",
                  label: "Superficie humana",
                  options: [
                    "NONE",
                    "WHATSAPP_COEXISTENCE",
                    "EXTERNAL_HELPDESK",
                  ],
                },
                { key: "support_hours", label: "Horario de soporte", max: 500 },
                {
                  key: "awaiting_human_policy",
                  label: "Mientras espera atención humana",
                  options: ["SILENT", "ACKNOWLEDGE"],
                },
              ]}
            />
            <ConfigurationFields
              prefix="approval"
              value={draft.configuration.approval_routes}
              onChange={(key, value) => update("approval_routes", key, value)}
              fields={[
                {
                  key: "high_risk_actions_expected",
                  label: "Requiere acciones de alto riesgo",
                  kind: "boolean",
                },
                {
                  key: "approver_emails",
                  label: "Correos de aprobadores (uno por línea)",
                  kind: "list",
                },
                {
                  key: "route_notes",
                  label: "Responsables y reglas de aprobación",
                  kind: "multiline",
                  max: 2000,
                },
              ]}
            />
            <p>
              Declarar una operación no la habilita. Los requisitos no
              soportados impedirán preparar una versión hasta su integración.
            </p>
          </details>
          <details>
            <summary>Modelo</summary>
            <ConfigurationFields
              prefix="model"
              value={draft.configuration.agent}
              onChange={(key, value) => update("agent", key, value)}
              fields={[
                {
                  key: "model",
                  label: "Modelo del borrador",
                  options: ["gpt-5.6-luna", "gpt-6-luna"],
                },
              ]}
            />
            <p>No se hacen llamadas al modelo al guardar.</p>
          </details>
          <details>
            <summary>Capacidades e integraciones</summary>
            <p>
              Solo lectura en esta fase. Una preferencia heredada no confirma
              que la herramienta esté conectada ni habilitada.
            </p>
            <pre>
              {JSON.stringify(
                {
                  capacidades: draft.configuration.capabilities,
                  integraciones: draft.configuration.integrations,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </div>
        <div className="configuration-save">
          <button type="submit" disabled={pending || refreshPending}>
            {pending ? "Guardando…" : "Guardar borrador"}
          </button>
          <button
            type="button"
            disabled
            title="Disponible tras adaptar pruebas y publicación"
          >
            Probar y publicar
          </button>
        </div>
      </form>
      <aside className="workspace-card">
        <h2>Información compartida de empresa</h2>
        <p>
          Este borrador usa la revisión {draft.company_revision}.{" "}
          {draft.company_update_available
            ? "Hay una actualización disponible."
            : "La información compartida está al día."}
        </p>
        <Link href={`/tenants/${draft.tenant_id}/settings`}>
          Editar información empresarial
        </Link>
        {draft.company_update_available ? (
          <button
            type="button"
            disabled={dirty || pending}
            onClick={async () =>
              setProfile(await compareCompanyProfile(draft.tenant_id))
            }
          >
            Comparar actualización de empresa
          </button>
        ) : null}
        {profile.profile ? (
          <form action={refreshAction}>
            <div className="workspace-detail-grid">
              <details>
                <summary>Datos usados en este borrador</summary>
                <pre>{JSON.stringify(draft.company_snapshot, null, 2)}</pre>
              </details>
              <details open>
                <summary>Datos compartidos actuales</summary>
                <pre>
                  {JSON.stringify(profile.profile.configuration, null, 2)}
                </pre>
              </details>
            </div>
            <input type="hidden" name="tenantId" value={draft.tenant_id} />
            <input
              type="hidden"
              name="agentId"
              value={draft.agent_instance_id}
            />
            <input type="hidden" name="revision" value={draft.revision} />
            <input
              type="hidden"
              name="companyRevision"
              value={profile.profile.revision}
            />
            <label>
              <input type="checkbox" name="confirm" required /> Incorporar estos
              datos al borrador sin cambiar la versión publicada
            </label>
            <button disabled={dirty || refreshPending || pending}>
              Incorporar información
            </button>
          </form>
        ) : null}
        {refresh.message || profile.message ? (
          <p role="status">{refresh.message ?? profile.message}</p>
        ) : null}
      </aside>
      {draft.validation_issues.length ? (
        <aside className="workspace-card">
          <h2>Pendiente antes de probar</h2>
          <ul>
            {draft.validation_issues.map((issue) => (
              <li key={issue.field + issue.code}>
                {issue.field}: {issue.message}
              </li>
            ))}
          </ul>
        </aside>
      ) : null}
    </section>
  );
}
