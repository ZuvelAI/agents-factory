"use client";

import Link from "next/link";
import { useActionState, useState } from "react";
import type {
  CompanyProfile,
  ConfigurationActionState,
  ConfigurationSection,
} from "../../lib/agent-configuration";
import {
  compareCompanyProfile,
  saveCompanyProfile,
  createConfigurationEntity,
  importLegacyConfiguration,
} from "./configuration-actions";
import { ConfigurationFields, companyFields } from "./configuration-fields";
import { useUnsavedConfiguration } from "./use-unsaved-configuration";

export function CompanyProfileForm({
  tenant,
  name,
  initial,
}: {
  tenant: string;
  name: string;
  initial: CompanyProfile | null;
}) {
  const [configuration, setConfiguration] = useState<ConfigurationSection>(
    initial?.configuration ?? {
      commercial_name: name,
      timezone: "America/Bogota",
      primary_locale: "es-CO",
    },
  );
  const [revision, setRevision] = useState(initial?.revision ?? 0),
    [comparison, setComparison] = useState<CompanyProfile | null>(null);
  const [savedConfiguration, setSavedConfiguration] = useState(configuration);
  useUnsavedConfiguration(
    JSON.stringify(configuration) !== JSON.stringify(savedConfiguration),
  );
  const [state, action, pending] = useActionState(
    async (previous: ConfigurationActionState, form: FormData) => {
      const result = await saveCompanyProfile(previous, form);
      if (result.profile) {
        setRevision(result.profile.revision);
        setConfiguration(result.profile.configuration);
        setSavedConfiguration(result.profile.configuration);
        setComparison(null);
      }
      return result;
    },
    { status: "idle" } as ConfigurationActionState,
  );
  return (
    <section className="workspace configuration-editor">
      <Link href={`/tenants/${tenant}`}>← Empresa</Link>
      <h1>Información de la empresa</h1>
      <p>
        Compartida como referencia. Guardar no cambia borradores existentes ni
        versiones publicadas.
      </p>
      <form action={action}>
        <input type="hidden" name="tenantId" value={tenant} />
        <input type="hidden" name="revision" value={revision} />
        <input
          type="hidden"
          name="configuration"
          value={JSON.stringify(configuration)}
        />
        <fieldset disabled={pending} className="configuration-fieldset">
          <ConfigurationFields
            prefix="company"
            fields={companyFields}
            value={configuration}
            onChange={(key, value) =>
              setConfiguration({ ...configuration, [key]: value })
            }
          />
        </fieldset>
        <button disabled={pending}>
          {pending ? "Guardando…" : "Guardar información empresarial"}
        </button>
      </form>
      {state.message ? <p role="status">{state.message}</p> : null}
      {state.status === "conflict" ? (
        <aside className="workspace-card">
          <h2>Otra revisión está guardada</h2>
          <button
            type="button"
            onClick={async () => {
              const result = await compareCompanyProfile(tenant);
              setComparison(result.profile ?? null);
            }}
          >
            Recargar para comparar
          </button>
          {comparison ? (
            <>
              <pre>{JSON.stringify(comparison.configuration, null, 2)}</pre>
              <button
                type="button"
                onClick={() => {
                  if (
                    window.confirm(
                      "¿Descartar tu texto y cargar la revisión guardada?",
                    )
                  ) {
                    setConfiguration(comparison.configuration);
                    setSavedConfiguration(comparison.configuration);
                    setRevision(comparison.revision);
                  }
                }}
              >
                Usar revisión guardada
              </button>
            </>
          ) : null}
        </aside>
      ) : null}
    </section>
  );
}

export function CreateEntityForm({ tenant }: { tenant?: string }) {
  const [name, setName] = useState(""),
    [slug, setSlug] = useState("");
  const [state, action, pending] = useActionState(createConfigurationEntity, {
    status: "idle",
  } as ConfigurationActionState);
  return (
    <section className="workspace configuration-editor">
      <Link href={tenant ? `/tenants/${tenant}` : "/tenants"}>← Volver</Link>
      <h1>{tenant ? "Nuevo agente" : "Nueva empresa"}</h1>
      <p>Crear no conecta WhatsApp ni publica respuestas.</p>
      <form action={action}>
        <input type="hidden" name="tenantId" value={tenant ?? ""} />
        <label>
          Nombre
          <input
            name="name"
            required
            maxLength={tenant ? 100 : 200}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        {!tenant ? (
          <label>
            Identificador único
            <input
              name="slug"
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              maxLength={100}
              required
              placeholder="mi-empresa"
              value={slug}
              onChange={(event) => setSlug(event.target.value)}
            />
          </label>
        ) : null}
        <button disabled={pending || state.status === "success"}>
          {pending ? "Creando…" : "Crear"}
        </button>
      </form>
      {state.message ? <p role="status">{state.message}</p> : null}
      {state.href ? (
        <Link className="workspace-secondary" href={state.href}>
          Abrir espacio creado →
        </Link>
      ) : null}
    </section>
  );
}

export function LegacyImportForm({
  tenant,
  agent,
  legacyRevision,
  companyRevision,
}: {
  tenant: string;
  agent: string;
  legacyRevision: number;
  companyRevision: number;
}) {
  const [state, action, pending] = useActionState(importLegacyConfiguration, {
    status: "idle",
  } as ConfigurationActionState);
  return (
    <section className="workspace configuration-editor">
      <Link href={`/tenants/${tenant}/agents/${agent}`}>
        ← Ficha del agente
      </Link>
      <h1>Preparar configuración editable</h1>
      <p>
        No existe un borrador independiente. Puedes importar la revisión
        anterior {legacyRevision} únicamente si el backend verifica que
        corresponde a esta instancia.
      </p>
      <p className="workspace-version">Agente destino: {agent}</p>
      <form action={action}>
        <input type="hidden" name="tenantId" value={tenant} />
        <input type="hidden" name="agentId" value={agent} />
        <input type="hidden" name="legacyRevision" value={legacyRevision} />
        <input type="hidden" name="companyRevision" value={companyRevision} />
        <label>
          <input name="confirm" type="checkbox" required /> Confirmo importar a
          esta instancia sin cambiar WhatsApp ni la versión publicada
        </label>
        <button disabled={pending || state.status === "success"}>
          Importar configuración anterior
        </button>
      </form>
      {state.message ? <p role="status">{state.message}</p> : null}
      {state.draft ? (
        <Link href={`/tenants/${tenant}/agents/${agent}/edit`}>
          Abrir borrador importado →
        </Link>
      ) : null}
    </section>
  );
}
