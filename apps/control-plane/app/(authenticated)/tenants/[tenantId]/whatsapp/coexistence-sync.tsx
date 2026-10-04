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

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isSyncStatusList(value: unknown): value is SyncStatus[] {
  if (!Array.isArray(value) || value.length > 2) return false;
  const seen = new Set<string>();
  return value.every((item) => {
    if (
      !isRecord(item) ||
      (item.sync_type !== "smb_app_state_sync" &&
        item.sync_type !== "history") ||
      seen.has(item.sync_type)
    )
      return false;
    seen.add(item.sync_type);
    if (item.state === "NOT_REQUESTED") {
      return item.request_id === null && item.reserved_at === null;
    }
    if (
      typeof item.reserved_at !== "string" ||
      !Number.isFinite(Date.parse(item.reserved_at))
    )
      return false;
    return item.state === "UNKNOWN"
      ? item.request_id === null
      : item.state === "ACCEPTED" &&
          typeof item.request_id === "string" &&
          item.request_id.length > 0 &&
          item.request_id.length <= 500;
  });
}

function isSyncObservations(value: unknown): value is SyncObservations {
  const countFields: (keyof SyncObservations)[] = [
    "active_contacts",
    "history_batches_received",
    "history_batches_imported",
    "history_batches_declined",
    "history_batches_pending",
  ];
  return (
    isRecord(value) &&
    countFields.every(
      (field) =>
        Number.isSafeInteger(value[field]) && (value[field] as number) >= 0,
    )
  );
}

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
    const [statusResult, observationResult] = await Promise.all([
      callAuthenticatedBackend<unknown>(`${basePath}/sync-status`),
      callAuthenticatedBackend<unknown>(`${basePath}/sync-observations`),
    ]);
    if (
      !isSyncStatusList(statusResult) ||
      !isSyncObservations(observationResult)
    ) {
      throw new Error("Invalid sync report");
    }
    statuses = statusResult;
    observations = observationResult;
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
