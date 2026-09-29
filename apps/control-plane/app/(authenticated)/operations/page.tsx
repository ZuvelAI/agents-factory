import { callAuthenticatedBackend } from "../../../lib/api";
import { resolveAccountUpdateAlert } from "./alert-actions";

type AlertSummary = { open_count: number };
type AccountUpdateAlert = {
  id: string;
  waba_id: string;
  event: string;
  display_phone_digits: string | null;
  occurred_at: string;
  reason: string;
  received_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
};

type SearchParams = {
  alerts?: string;
  offset?: string;
  alertResolution?: string;
};

const UUID_PATTERN = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const PAGE_SIZE = 50;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isDate(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function isAlertSummary(value: unknown): value is AlertSummary {
  return (
    isRecord(value) &&
    Number.isSafeInteger(value.open_count) &&
    (value.open_count as number) >= 0
  );
}

function isAccountUpdateAlertList(
  value: unknown,
): value is AccountUpdateAlert[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        isRecord(item) &&
        typeof item.id === "string" &&
        UUID_PATTERN.test(item.id) &&
        typeof item.waba_id === "string" &&
        typeof item.event === "string" &&
        (item.display_phone_digits === null ||
          typeof item.display_phone_digits === "string") &&
        isDate(item.occurred_at) &&
        typeof item.reason === "string" &&
        isDate(item.received_at) &&
        (item.resolved_at === null || isDate(item.resolved_at)) &&
        (item.resolved_by === null ||
          (typeof item.resolved_by === "string" &&
            UUID_PATTERN.test(item.resolved_by))) &&
        (item.resolution_note === null ||
          typeof item.resolution_note === "string"),
    )
  );
}

function displayDate(value: string): string {
  return new Date(value).toLocaleString("es-CO", {
    timeZone: "America/Bogota",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function noticeFor(outcome: string | undefined): string | null {
  switch (outcome) {
    case "resolved":
      return "La alerta quedó cerrada con una nota de revisión.";
    case "conflict":
      return "La alerta ya había sido cerrada. Actualizamos la lista para mostrar su estado.";
    case "invalid":
      return "Revisa el identificador, la nota y la confirmación antes de cerrar la alerta.";
    case "error":
      return "No se pudo cerrar la alerta. Inténtalo de nuevo cuando el servicio esté disponible.";
    default:
      return null;
  }
}

export default async function OperationsPage({
  searchParams,
}: {
  searchParams?: Promise<SearchParams>;
}) {
  const query = (await searchParams) ?? {};
  const view = query.alerts === "resolved" ? "resolved" : "open";
  const offset =
    typeof query.offset === "string" &&
    /^\d+$/.test(query.offset) &&
    Number.isSafeInteger(Number(query.offset)) &&
    Number(query.offset) <= 1_000_000
      ? Number(query.offset)
      : 0;

  let summary: AlertSummary | null = null;
  let alerts: AccountUpdateAlert[] | null = null;
  try {
    const [summaryResult, listResult] = await Promise.all([
      callAuthenticatedBackend<unknown>(
        "/admin/whatsapp/account-update-alerts/summary",
      ),
      callAuthenticatedBackend<unknown>(
        `/admin/whatsapp/account-update-alerts?status=${view}&limit=${PAGE_SIZE}&offset=${offset}`,
      ),
    ]);
    if (
      isAlertSummary(summaryResult) &&
      isAccountUpdateAlertList(listResult) &&
      listResult.length <= PAGE_SIZE &&
      listResult.every((alert) =>
        view === "open"
          ? alert.resolved_at === null &&
            alert.resolved_by === null &&
            alert.resolution_note === null
          : alert.resolved_at !== null &&
            alert.resolved_by !== null &&
            alert.resolution_note !== null,
      )
    ) {
      summary = summaryResult;
      alerts = listResult;
    }
  } catch {
    // An unavailable backend is not an empty alert queue.
  }

  const notice = noticeFor(query.alertResolution);
  const base =
    view === "resolved"
      ? "/operations?alerts=resolved"
      : "/operations?alerts=open";

  return (
    <main className="workspace-page operations-alerts">
      <p className="eyebrow">OPERACIONES</p>
      <h1>Alertas de WhatsApp</h1>
      <p className="workspace-description">
        Revisa los cambios ambiguos de cuentas y registra manualmente el
        resultado. Cerrar una alerta no cambia la conexión de WhatsApp ni el
        control del agente.
      </p>

      {notice && (
        <p className="operations-alert-notice" role="status">
          {notice}
        </p>
      )}

      {summary === null || alerts === null ? (
        <section className="operations-alert-unavailable" role="alert">
          <h2>No se pudieron consultar las alertas</h2>
          <p>
            El estado no está disponible. Vuelve a intentar cuando el servicio
            responda.
          </p>
        </section>
      ) : (
        <section aria-labelledby="operations-alert-heading">
          <h2 id="operations-alert-heading">
            {summary.open_count}{" "}
            {summary.open_count === 1
              ? "alerta pendiente"
              : "alertas pendientes"}
          </h2>
          <nav className="operations-alert-tabs" aria-label="Estado de alertas">
            <a
              href="/operations"
              aria-current={view === "open" ? "page" : undefined}
            >
              Abiertas
            </a>
            <a
              href="/operations?alerts=resolved"
              aria-current={view === "resolved" ? "page" : undefined}
            >
              Historial de alertas
            </a>
          </nav>

          {alerts.length === 0 ? (
            <p className="operations-alert-empty">
              {view === "open"
                ? "No hay alertas abiertas en esta página."
                : "No hay alertas cerradas en esta página."}
            </p>
          ) : (
            <ul className="operations-alert-list">
              {alerts.map((alert) => (
                <li key={alert.id}>
                  <div className="operations-alert-details">
                    <strong>{alert.event}</strong>
                    <dl>
                      <div>
                        <dt>Cuenta de WhatsApp</dt>
                        <dd>{alert.waba_id}</dd>
                      </div>
                      <div>
                        <dt>Número</dt>
                        <dd>
                          {alert.display_phone_digits
                            ? `+${alert.display_phone_digits}`
                            : "No disponible"}
                        </dd>
                      </div>
                      <div>
                        <dt>Motivo</dt>
                        <dd>{alert.reason}</dd>
                      </div>
                      <div>
                        <dt>Ocurrió</dt>
                        <dd>{displayDate(alert.occurred_at)}</dd>
                      </div>
                      <div>
                        <dt>Recibida</dt>
                        <dd>{displayDate(alert.received_at)}</dd>
                      </div>
                    </dl>
                  </div>
                  {view === "resolved" ? (
                    <div className="operations-alert-resolution">
                      <p>
                        <strong>Nota:</strong> {alert.resolution_note}
                      </p>
                      <p>
                        <strong>Cerrada:</strong>{" "}
                        {displayDate(alert.resolved_at!)}
                      </p>
                      <p>
                        <strong>Responsable:</strong> {alert.resolved_by}
                      </p>
                    </div>
                  ) : (
                    <details className="operations-alert-close">
                      <summary>Registrar revisión y cerrar</summary>
                      <form action={resolveAccountUpdateAlert}>
                        <input type="hidden" name="alertId" value={alert.id} />
                        <input type="hidden" name="confirmed" value="resolve" />
                        <label htmlFor={`note-${alert.id}`}>
                          Nota de revisión
                        </label>
                        <textarea
                          id={`note-${alert.id}`}
                          name="note"
                          required
                          maxLength={500}
                          rows={3}
                        />
                        <button type="submit">Confirmar cierre</button>
                      </form>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          )}

          <nav
            className="operations-alert-pagination"
            aria-label="Páginas de alertas"
          >
            {offset > 0 && (
              <a href={`${base}&offset=${Math.max(0, offset - PAGE_SIZE)}`}>
                Anterior
              </a>
            )}
            {alerts.length === PAGE_SIZE && (
              <a href={`${base}&offset=${offset + PAGE_SIZE}`}>Siguiente</a>
            )}
          </nav>
        </section>
      )}
    </main>
  );
}
