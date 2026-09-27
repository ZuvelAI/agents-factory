import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { callAuthenticatedBackend } from "../../lib/api";
import { CoexistenceSync } from "../../app/(authenticated)/tenants/[tenantId]/whatsapp/coexistence-sync";

vi.mock("../../lib/api", () => ({
  callAuthenticatedBackend: vi.fn(),
}));

const getBackend = vi.mocked(callAuthenticatedBackend);
const tenantId = "019c2000-0000-7000-8000-000000000101";
const accountId = "019c2000-0000-7000-8000-000000000202";

beforeEach(() => {
  getBackend.mockReset();
});

describe("coexistence sync visibility", () => {
  it("separates Meta request acceptance from observed data and completion", async () => {
    getBackend.mockImplementation(async (path) => {
      if (path.endsWith("/sync-status")) {
        return [
          {
            sync_type: "smb_app_state_sync",
            state: "ACCEPTED",
            request_id: "meta-contacts-123",
            reserved_at: "2026-09-26T12:00:00Z",
          },
          {
            sync_type: "history",
            state: "ACCEPTED",
            request_id: "meta-history-123",
            reserved_at: "2026-09-26T12:00:00Z",
          },
        ];
      }
      if (path.endsWith("/sync-observations")) {
        return {
          active_contacts: 3,
          history_batches_received: 2,
          history_batches_imported: 1,
          history_batches_declined: 0,
          history_batches_pending: 1,
        };
      }
      throw new Error("unexpected endpoint");
    });

    const markup = renderToStaticMarkup(
      await CoexistenceSync({ tenantId, accountId }),
    );

    expect(markup).toContain("Contactos: solicitud aceptada por Meta");
    expect(markup).toContain("Historial: solicitud aceptada por Meta");
    expect(markup).toContain("Contactos activos: 3");
    expect(markup).toContain("Lotes de historial pendientes: 1");
    expect(markup).toContain(
      "no confirma que la sincronización haya terminado",
    );
    expect(markup).not.toContain("meta-contacts-123");
    expect(markup).not.toContain("meta-history-123");
  });

  it("does not call an omitted status a request that was never sent", async () => {
    getBackend.mockImplementation(async (path) => {
      if (path.endsWith("/sync-status")) {
        return [
          {
            sync_type: "smb_app_state_sync",
            state: "UNKNOWN",
            request_id: null,
            reserved_at: "2026-09-26T12:00:00Z",
          },
        ];
      }
      return {
        active_contacts: 0,
        history_batches_received: 0,
        history_batches_imported: 0,
        history_batches_declined: 0,
        history_batches_pending: 0,
      };
    });

    const markup = renderToStaticMarkup(
      await CoexistenceSync({ tenantId, accountId }),
    );

    expect(markup).toContain(
      "Contactos: resultado incierto; requiere revisión manual",
    );
    expect(markup).toContain("Historial: estado no disponible");
    expect(markup).not.toContain("Historial: solicitud aún no registrada");
  });

  it("contains a malformed backend response instead of breaking the account page", async () => {
    getBackend.mockImplementation(async (path) =>
      path.endsWith("/sync-status") ? {} : { active_contacts: 0 },
    );

    const markup = renderToStaticMarkup(
      await CoexistenceSync({ tenantId, accountId }),
    );

    expect(markup).toContain(
      "No se pudo consultar el estado de sincronización.",
    );
  });

  it("does not display partial observation counts as a complete report", async () => {
    getBackend.mockImplementation(async (path) =>
      path.endsWith("/sync-status")
        ? [
            {
              sync_type: "smb_app_state_sync",
              state: "NOT_REQUESTED",
              request_id: null,
              reserved_at: null,
            },
          ]
        : { active_contacts: 2 },
    );

    const markup = renderToStaticMarkup(
      await CoexistenceSync({ tenantId, accountId }),
    );

    expect(markup).toContain(
      "No se pudo consultar el estado de sincronización.",
    );
    expect(markup).not.toContain("Contactos activos: 2");
  });
});
