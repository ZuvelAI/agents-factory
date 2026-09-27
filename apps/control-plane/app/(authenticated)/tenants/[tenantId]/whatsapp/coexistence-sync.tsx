import { callAuthenticatedBackend } from "../../../../../lib/api";

type SyncType = "smb_app_state_sync" | "history";
type SyncState = "NOT_REQUESTED" | "UNKNOWN" | "ACCEPTED";

type SyncStatus = {
  sync_type: SyncType;
  state: SyncState;
  request_id: string | null;
  reserved_at: string | null;
};

type SyncObservations = {
  active_contacts: number;
  history_batches_received: number;
  history_batches_imported: number;
  history_batches_declined: number;
  history_batches_pending: number;
};

function requestDescription(status: SyncStatus | undefined): string {
  if (!status) return "estado no disponible";
  switch (status.state) {
    case "ACCEPTED":
      return "solicitud aceptada por Meta";
    case "UNKNOWN":
      return "resultado incierto; requiere revisión manual";
    case "NOT_REQUESTED":
      return "solicitud aún no registrada";
  }
}

export async function CoexistenceSync({
  tenantId,
  accountId,
}: {
  tenantId: string;
  accountId: string;
}) {
  const basePath = `/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp/${encodeURIComponent(accountId)}`;
  let statuses: SyncStatus[];
  let observations: SyncObservations;
  try {
    [statuses, observations] = await Promise.all([
      callAuthenticatedBackend<SyncStatus[]>(`${basePath}/sync-status`),
      callAuthenticatedBackend<SyncObservations>(
        `${basePath}/sync-observations`,
      ),
    ]);
    if (!Array.isArray(statuses)) throw new Error("Invalid sync statuses");
    const countFields: (keyof SyncObservations)[] = [
      "active_contacts",
      "history_batches_received",
      "history_batches_imported",
      "history_batches_declined",
      "history_batches_pending",
    ];
    if (
      !observations ||
      countFields.some(
        (field) =>
          !Number.isSafeInteger(observations[field]) || observations[field] < 0,
      )
    ) {
      throw new Error("Invalid sync observations");
    }
  } catch {
    return (
      <section aria-label="Sincronización de coexistencia">
        <h3>Sincronización inicial</h3>
        <p role="status">No se pudo consultar el estado de sincronización.</p>
      </section>
    );
  }

  return (
    <section aria-label="Sincronización de coexistencia">
      <h3>Sincronización inicial</h3>
      <p>
        Contactos:{" "}
        {requestDescription(
          statuses.find((item) => item.sync_type === "smb_app_state_sync"),
        )}
      </p>
      <p>
        Historial:{" "}
        {requestDescription(
          statuses.find((item) => item.sync_type === "history"),
        )}
      </p>
      <p>Contactos activos: {observations.active_contacts}</p>
      <p>
        Lotes de historial recibidos: {observations.history_batches_received}
      </p>
      <p>
        Lotes de historial importados: {observations.history_batches_imported}
      </p>
      <p>
        Lotes de historial rechazados: {observations.history_batches_declined}
      </p>
      <p>
        Lotes de historial pendientes: {observations.history_batches_pending}
      </p>
      <p>
        La aceptación de Meta y estos recuentos locales no confirma que la
        sincronización haya terminado.
      </p>
    </section>
  );
}
