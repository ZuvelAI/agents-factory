import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";
import ConversationsPage from "../../app/(authenticated)/conversations/page";
import { callAuthenticatedBackend } from "../../lib/api";
vi.mock("../../lib/api", () => ({ callAuthenticatedBackend: vi.fn() }));
const backend = vi.mocked(callAuthenticatedBackend);
const tenant = "019c2000-0000-7000-8000-000000000111";
const conversation = "019c2000-0000-7000-8000-000000000222";
beforeEach(() => {
  backend.mockReset();
});
it("renders stored conversations and escapes message content", async () => {
  backend.mockImplementation(async (path) =>
    path === "/admin/tenants"
      ? [{ id: tenant, name: "Zuvel" }]
      : path.endsWith("/messages?limit=50&offset=0")
        ? [
            {
              id: conversation,
              direction: "inbound",
              message_type: "text",
              text: "prueba <script>unsafe</script>",
              created_at: "2026-10-13T01:00:00Z",
            },
          ]
        : [
            {
              id: conversation,
              customer_wa_id: "CO.123",
              control_state: "AI_ACTIVE",
              updated_at: "2026-10-13T01:00:00Z",
            },
          ],
  );
  const markup = renderToStaticMarkup(
    await ConversationsPage({
      searchParams: Promise.resolve({ tenant, conversation }),
    }),
  );
  expect(markup).toContain("CO.123");
  expect(markup).toContain("prueba &lt;script&gt;unsafe&lt;/script&gt;");
  expect(markup).not.toContain("<script>unsafe</script>");
  expect(markup).not.toContain("Todavía no hay conversaciones");
  expect(markup).not.toContain("Enviar mensaje");
});
it("distinguishes backend failure from an empty list", async () => {
  backend.mockRejectedValue(new Error("private failure"));
  const markup = renderToStaticMarkup(await ConversationsPage({}));
  expect(markup).toContain("No se pudieron consultar");
  expect(markup).not.toContain("private failure");
});
it("shows an honest empty state after successful reads", async () => {
  backend.mockImplementation(async (path) =>
    path === "/admin/tenants" ? [{ id: tenant, name: "Zuvel" }] : [],
  );
  const markup = renderToStaticMarkup(await ConversationsPage({}));
  expect(markup).toContain(
    "No hay conversaciones registradas para este cliente",
  );
  expect(markup).not.toContain("Preparar WhatsApp");
});

it("does not fetch messages for an unlisted tenant or conversation", async () => {
  backend.mockResolvedValue([{ id: tenant, name: "Zuvel" }]);
  const markup = renderToStaticMarkup(
    await ConversationsPage({
      searchParams: Promise.resolve({ tenant: "../../private", conversation }),
    }),
  );
  expect(markup).toContain("No se pudieron consultar");
  expect(backend.mock.calls.map((call) => call[0])).toEqual(["/admin/tenants"]);
});

it("does not present malformed data as an empty conversation list", async () => {
  backend.mockImplementation(async (path) =>
    path === "/admin/tenants"
      ? [{ id: tenant, name: "Zuvel" }]
      : [
          {
            id: conversation,
            customer_wa_id: "CO.123",
            control_state: "constructor",
            updated_at: "invalid",
          },
        ],
  );
  const markup = renderToStaticMarkup(await ConversationsPage({}));
  expect(markup).toContain("No se pudieron consultar");
  expect(markup).not.toContain("No hay conversaciones registradas");
});
