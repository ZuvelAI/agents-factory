import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OperationsPage from "../../app/(authenticated)/operations/page";
import OperationsLoading from "../../app/(authenticated)/operations/loading";
import { callAuthenticatedBackend } from "../../lib/api";

vi.mock("../../lib/api", () => ({ callAuthenticatedBackend: vi.fn() }));
vi.mock("../../app/(authenticated)/operations/alert-actions", () => ({
  resolveAccountUpdateAlert: vi.fn(),
}));

const backend = vi.mocked(callAuthenticatedBackend);
const alertId = "019c2000-0000-7000-8000-000000000777";
const actorId = "019c2000-0000-7000-8000-000000000111";
const openAlert = {
  id: alertId,
  waba_id: "waba-123",
  event: "ACCOUNT_OFFBOARDED",
  display_phone_digits: "15550123456",
  occurred_at: "2026-09-28T10:00:00Z",
  reason: "unmatched",
  received_at: "2026-09-28T10:01:00Z",
  resolved_at: null,
  resolved_by: null,
  resolution_note: null,
};

beforeEach(() => {
  backend.mockReset();
});

describe("Operations alert triage", () => {
  it("shows a loading state without claiming the queue is empty", () => {
    const markup = renderToStaticMarkup(OperationsLoading());
    expect(markup).toContain("Consultando alertas");
    expect(markup).not.toContain("0 alertas pendientes");
  });

  it("shows the open count and requires a note for a confirmed close", async () => {
    backend.mockImplementation(async (path) =>
      path.endsWith("/summary") ? { open_count: 1 } : [openAlert],
    );

    const markup = renderToStaticMarkup(await OperationsPage({}));

    expect(markup).toContain("1 alerta pendiente");
    expect(markup).toContain("ACCOUNT_OFFBOARDED");
    expect(markup).toContain("waba-123");
    expect(markup).toContain('name="alertId"');
    expect(markup).toContain('name="note"');
    expect(markup).toContain("required");
    expect(markup).toContain('name="confirmed" value="resolve"');
    expect(markup).toContain("Confirmar cierre");
    expect(markup).toContain(
      "No incluyas tokens, credenciales ni contenido de mensajes",
    );
    expect(backend).toHaveBeenCalledWith(
      "/admin/whatsapp/account-update-alerts?status=open&limit=50&offset=0",
    );
  });

  it("shows resolved history as plain text, with actor and time", async () => {
    backend.mockImplementation(async (path) =>
      path.endsWith("/summary")
        ? { open_count: 0 }
        : [
            {
              ...openAlert,
              resolved_at: "2026-09-28T11:00:00Z",
              resolved_by: actorId,
              resolution_note: "Reviewed <script>alert(1)</script>",
            },
          ],
    );

    const markup = renderToStaticMarkup(
      await OperationsPage({
        searchParams: Promise.resolve({ alerts: "resolved" }),
      }),
    );

    expect(markup).toContain("Historial de alertas");
    expect(markup).toContain(actorId);
    expect(markup).toContain("28/09/2026");
    expect(markup).toContain("Reviewed &lt;script&gt;alert(1)&lt;/script&gt;");
    expect(markup).not.toContain("<script>alert(1)</script>");
    expect(markup).not.toContain('name="note"');
    expect(backend).toHaveBeenCalledWith(
      "/admin/whatsapp/account-update-alerts?status=resolved&limit=50&offset=0",
    );
  });

  it("selects a bounded history page and keeps paging links", async () => {
    backend.mockImplementation(async (path) =>
      path.endsWith("/summary")
        ? { open_count: 3 }
        : Array.from({ length: 50 }, () => ({
            ...openAlert,
            resolved_at: "2026-09-28T11:00:00Z",
            resolved_by: actorId,
            resolution_note: "Reviewed",
          })),
    );

    const markup = renderToStaticMarkup(
      await OperationsPage({
        searchParams: Promise.resolve({ alerts: "resolved", offset: "50" }),
      }),
    );

    expect(markup).toContain("alerts=resolved&amp;offset=0");
    expect(markup).toContain("alerts=resolved&amp;offset=100");
    expect(backend).toHaveBeenCalledWith(
      "/admin/whatsapp/account-update-alerts?status=resolved&limit=50&offset=50",
    );
  });

  it("shows an unavailable state for failed or malformed backend data", async () => {
    backend.mockRejectedValueOnce(new Error("offline"));
    const unavailable = renderToStaticMarkup(await OperationsPage({}));
    expect(unavailable).toContain("No se pudieron consultar las alertas");
    expect(unavailable).not.toContain("0 alertas pendientes");

    backend.mockImplementation(async (path) =>
      path.endsWith("/summary") ? { open_count: "0" } : [openAlert],
    );
    const malformed = renderToStaticMarkup(await OperationsPage({}));
    expect(malformed).toContain("No se pudieron consultar las alertas");
    expect(malformed).not.toContain("0 alertas pendientes");
  });
});
