import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";
import Page from "../../app/(authenticated)/conversation-log/page";
import { callAuthenticatedBackend } from "../../lib/api";
vi.mock("../../lib/api", () => ({ callAuthenticatedBackend: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: () => undefined }),
}));
const backend = vi.mocked(callAuthenticatedBackend);
const tenant = "019c2000-0000-7000-8000-000000000102";
const agent = "019c2000-0000-7000-8000-000000000501";
const conversation = "019c2000-0000-7000-8000-000000000303";
const account = "019c2000-0000-7000-8000-000000000202";
beforeEach(() => {
  backend.mockReset();
});
function seed() {
  backend.mockImplementation(async (path) =>
    path.includes("/accounts")
      ? { items: [], next_cursor: null }
      : path.includes("/messages")
        ? {
            items: [
              {
                id: agent,
                arrival_sequence: 1,
                direction: "outbound",
                message_type: "text",
                text: "Respuesta <script>no ejecutar</script>",
                created_at: "2026-10-14T15:00:00Z",
                agent_id: agent,
                agent_spec_id: agent,
                delivery_status: "DELIVERED",
              },
            ],
            next_cursor: "older",
          }
        : path.includes("/conversations")
          ? {
              items: [
                {
                  id: conversation,
                  account_id: account,
                  customer_wa_id: "CO.123",
                  contact_name: "Ana <script>no ejecutar</script>",
                  contact_username: "ana.ventas",
                  contact_phone_number: "+573000000001",
                  control_state: "AI_ACTIVE",
                  updated_at: "2026-10-14T15:00:00Z",
                  agent_ids: [agent],
                },
              ],
              next_cursor: "next",
            }
          : path.endsWith("/agents")
            ? { items: [], next_cursor: null, company_name: "Zuvel" }
            : {
                items: [
                  { id: tenant, name: "Zuvel", agent_count: 0, agents: [] },
                ],
                next_cursor: null,
              },
  );
}
it("preserves filters, shows stored delivery and escapes text without assigning all messages to active agent", async () => {
  seed();
  const html = renderToStaticMarkup(
    await Page({
      searchParams: Promise.resolve({ tenant, agent, account, conversation }),
    }),
  );
  expect(html).toContain("Respuesta &lt;script&gt;no ejecutar&lt;/script&gt;");
  expect(html).toContain("Entregado");
  expect(html).toContain(`agent=${agent}`);
  expect(html).toContain(`account=${account}`);
  expect(html).toContain("Versión registrada");
  expect(html).not.toContain("Enviar mensaje");
  expect(html).not.toContain("Preparar WhatsApp");
  expect(html).toContain("Ana &lt;script&gt;no ejecutar&lt;/script&gt;");
  expect(html).toContain("@ana.ventas");
  expect(html).toContain("+573000000001");
});
it("does not convert backend failure or malformed data into empty conversations", async () => {
  backend.mockRejectedValue(new Error("private database detail"));
  const html = renderToStaticMarkup(await Page({}));
  expect(html).toContain("No pudimos consultar las conversaciones");
  expect(html).not.toContain("private database detail");
  expect(html).not.toContain("No hay conversaciones para estos filtros");
});
it("shows successful empty reads honestly and rejects path traversal before access", async () => {
  backend.mockImplementation(async (path) =>
    path.includes("/accounts")
      ? { items: [], next_cursor: null }
      : path.includes("/conversations")
        ? { items: [], next_cursor: null }
        : path.endsWith("/agents")
          ? { items: [], next_cursor: null, company_name: "Zuvel" }
          : {
              items: [
                { id: tenant, name: "Zuvel", agent_count: 0, agents: [] },
              ],
              next_cursor: null,
            },
  );
  expect(
    renderToStaticMarkup(
      await Page({ searchParams: Promise.resolve({ tenant }) }),
    ),
  ).toContain("No hay conversaciones para estos filtros");
  backend.mockClear();
  expect(
    renderToStaticMarkup(
      await Page({
        searchParams: Promise.resolve({ tenant: "../../private" }),
      }),
    ),
  ).toContain("No pudimos consultar las conversaciones");
  expect(backend).not.toHaveBeenCalled();
});

it("offers bounded selector pagination and unbound account options", async () => {
  backend.mockImplementation(async (path) =>
    path.includes("/accounts")
      ? {
          items: [
            {
              account_id: account,
              display_number: "+573000000000",
              version_id: null,
              connection_status: "unknown",
              checked_at: null,
            },
          ],
          next_cursor: "accounts-next",
        }
      : path.endsWith("/agents")
        ? { items: [], company_name: "Zuvel", next_cursor: "agents-next" }
        : path.includes("/conversations")
          ? { items: [], next_cursor: null }
          : {
              items: [
                { id: tenant, name: "Zuvel", agent_count: 0, agents: [] },
              ],
              next_cursor: "companies-next",
            },
  );
  const html = renderToStaticMarkup(
    await Page({ searchParams: Promise.resolve({ tenant }) }),
  );
  expect(html).toContain("Más empresas para filtrar");
  expect(html).toContain("Más agentes para filtrar");
  expect(html).toContain("Más cuentas para filtrar");
  expect(html).toContain("+573000000000");
  expect(html).toContain("companiesCursor=companies-next");
});

it("keeps a bookmarked conversation open when it is outside the current list page", async () => {
  seed();
  const previous = backend.getMockImplementation()!;
  backend.mockImplementation(async (path, options) =>
    path.includes("/messages")
      ? previous(path, options)
      : path.includes(`/conversations/${conversation}`)
        ? {
            id: conversation,
            account_id: account,
            customer_wa_id: "Hilo conservado",
            control_state: "AI_ACTIVE",
            updated_at: "2026-10-14T15:00:00Z",
            last_activity_at: "2026-10-15T15:00:00Z",
            agent_ids: [agent],
          }
        : path.includes("/conversations")
          ? { items: [], next_cursor: null }
          : previous(path, options),
  );
  const html = renderToStaticMarkup(
    await Page({
      searchParams: Promise.resolve({ tenant, agent, conversation }),
    }),
  );
  expect(html).toContain("Hilo conservado");
  expect(html).toContain("Respuesta &lt;script&gt;no ejecutar&lt;/script&gt;");
  expect(html).not.toContain("Selecciona una conversación");
});
