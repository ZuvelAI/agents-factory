import Link from "next/link";
import type {
  AgentOverview,
  AgentConfigurationView,
  FeatureSummary,
} from "../../lib/agent-workspace";
import { StatusSummary } from "./status-summary";
import { AgentOperationControls } from "./agent-operation-controls";
import type { AgentOperationView } from "../../lib/agent-operations";

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="workspace-field">
      <dt>{label}</dt>
      <dd>{value || "No disponible en esta versión"}</dd>
    </div>
  );
}
function Features({
  items,
  empty,
}: {
  items: FeatureSummary[];
  empty: string;
}) {
  return items.length ? (
    <ul className="workspace-features">
      {items.map((item) => (
        <li key={item.key}>
          <strong>{item.label}</strong>
          <span className="workspace-tag">
            {item.availability === "available"
              ? item.enabled
                ? "Habilitado"
                : "Deshabilitado"
              : item.availability === "unavailable"
                ? "No disponible"
                : "Sin verificar"}
          </span>
          {item.reason ? (
            <p className="workspace-muted">{item.reason}</p>
          ) : null}
        </li>
      ))}
    </ul>
  ) : (
    <p className="workspace-muted">{empty}</p>
  );
}
function ConfigurationDetails({
  configuration,
}: {
  configuration: AgentConfigurationView;
}) {
  return (
    <div className="workspace-sections">
      <details open>
        <summary>Identidad y comportamiento</summary>
        <dl>
          <Field
            label="Nombre empresarial de la versión"
            value={configuration.name}
          />
          <Field label="Propósito" value={configuration.purpose} />
          <Field label="Tono de comunicación" value={configuration.tone} />
          <Field label="Instrucciones" value={configuration.instructions} />
        </dl>
      </details>
      <details>
        <summary>Conocimiento de la empresa</summary>
        <p className="workspace-muted">
          Contenido aprobado disponible en esta versión. Una referencia no
          significa que hayamos descargado o leído un archivo.
        </p>
        <p className="workspace-prose">
          {configuration.knowledge_summary ||
            "No hay un resumen aprobado disponible en esta versión."}
        </p>
      </details>
      <details>
        <summary>Capacidades</summary>
        <Features
          items={configuration.capabilities}
          empty="No hay capacidades declaradas"
        />
      </details>
      <details>
        <summary>Integraciones</summary>
        <Features
          items={configuration.integrations}
          empty="No hay integraciones declaradas"
        />
      </details>
      <details>
        <summary>Modelo y operación</summary>
        <dl>
          <Field label="Modelo" value={configuration.model} />
        </dl>
        <p className="workspace-muted">
          Los controles operativos y de permisos permanecen en la administración
          avanzada durante esta entrega.
        </p>
      </details>
    </div>
  );
}
export function AgentOverviewPanel({
  overview,
  operation = null,
}: {
  overview: AgentOverview;
  operation?: AgentOperationView | null;
}) {
  const { summary, published, draft } = overview;
  const channelVersions = overview.channel_versions ?? [];
  return (
    <section className="workspace">
      <Link className="workspace-back" href={`/tenants/${summary.tenant_id}`}>
        ← Agentes de la empresa
      </Link>
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">Ficha del agente</p>
          <h1>{summary.display_name}</h1>
          <StatusSummary agent={summary} />
        </div>
        <div>
          <Link
            className="workspace-secondary"
            href={`/prospects?tenant=${summary.tenant_id}&agent=${summary.id}`}
          >
            Ver prospectos
          </Link>
          <Link
            className="workspace-secondary"
            href={`/tenants/${summary.tenant_id}/agents/${summary.id}/edit`}
          >
            Editar borrador
          </Link>
          <Link
            className="workspace-secondary"
            href={`/tenants/${summary.tenant_id}/agents/${summary.id}/test`}
          >
            Probar cambios
          </Link>
          <small className="workspace-block workspace-muted">
            Pruebas aisladas; publicar requiere revisión y confirmación
          </small>
        </div>
      </header>
      <AgentOperationControls
        tenantId={summary.tenant_id}
        agentId={summary.id}
        initial={operation}
      />
      <div className="workspace-detail-grid">
        <div>
          <article className="workspace-card">
            <h2>Configuración publicada</h2>
            {channelVersions.length ? (
              <>
                <h3>Versiones asignadas por canal</h3>
                <p className="workspace-muted">
                  Cada número utiliza su versión asignada, aunque exista una
                  publicación posterior.
                </p>
                {channelVersions.map((version) => (
                  <details
                    className="workspace-sections"
                    key={version.version_id}
                    open
                  >
                    <summary>Versión asignada {version.version_id}</summary>
                    <p className="workspace-muted workspace-version">
                      Cuentas:{" "}
                      {version.account_ids
                        .map(
                          (id) =>
                            summary.channel_accounts.find(
                              (c) => c.account_id === id,
                            )?.display_number ?? id,
                        )
                        .join(", ")}
                    </p>
                    {version.configuration ? (
                      <ConfigurationDetails
                        configuration={version.configuration}
                      />
                    ) : (
                      <p>Configuración no disponible</p>
                    )}
                  </details>
                ))}
              </>
            ) : published ? (
              <>
                <p className="workspace-muted workspace-version">
                  Versión {summary.published_version_id}
                </p>
                <ConfigurationDetails configuration={published} />
              </>
            ) : (
              <p className="workspace-muted">
                Este agente aún no tiene una versión publicada
              </p>
            )}
          </article>
          {channelVersions.length && published ? (
            <details className="workspace-draft">
              <summary>Última publicación registrada</summary>
              <p className="workspace-muted">
                Referencia histórica, no una asignación común para todos los
                números.
              </p>
              <ConfigurationDetails configuration={published} />
            </details>
          ) : null}
          {draft ? (
            <details className="workspace-draft">
              <summary>Borrador sin publicar</summary>
              <p className="workspace-muted">
                Estos datos no modifican la configuración publicada.
              </p>
              <ConfigurationDetails configuration={draft} />
            </details>
          ) : null}
        </div>
        <aside className="workspace-card workspace-detail-aside">
          <h2>Canales y contexto</h2>
          {summary.channel_accounts.length ? (
            summary.channel_accounts.map((channel) => (
              <div key={channel.account_id}>
                <strong>
                  {channel.display_number || "Número no disponible"}
                </strong>
                {channel.version_id ? (
                  <p className="workspace-version">
                    Versión asignada: {channel.version_id}
                  </p>
                ) : null}
                <p>
                  {
                    {
                      connected: "Conexión verificada",
                      disconnected: "Desconectado",
                      review_required: "Requiere revisión",
                      unknown: "Conexión sin verificar",
                    }[channel.connection_status]
                  }
                </p>
                <p className="workspace-muted">
                  Última comprobación:{" "}
                  {channel.checked_at
                    ? new Date(channel.checked_at).toLocaleString("es-CO", {
                        timeZone: "America/Bogota",
                      })
                    : "No disponible"}
                </p>
              </div>
            ))
          ) : (
            <p className="workspace-muted">
              Sin canal asignado. No se iniciará ninguna conexión
              automáticamente.
            </p>
          )}
          <Link
            className="workspace-open"
            href={`/conversation-log?tenant=${summary.tenant_id}&agent=${summary.id}`}
          >
            Ver conversaciones →
          </Link>
          <details>
            <summary>Administración avanzada</summary>
            <p className="workspace-muted">
              La configuración heredada es de la empresa. No es un editor
              independiente de este agente.
            </p>
            <Link href={`/tenants/${summary.tenant_id}/onboarding/agent`}>
              Abrir configuración anterior
            </Link>
            <br />
            <Link href={`/tenants/${summary.tenant_id}/onboarding/production`}>
              Publicación e historial existentes
            </Link>
          </details>
          {overview.unavailable_sections.map((item) => (
            <p className="workspace-muted" key={item}>
              {item}
            </p>
          ))}
        </aside>
      </div>
    </section>
  );
}
