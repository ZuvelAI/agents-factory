import { expect, it, vi } from "vitest";
import {
  parseProspectPage,
  parseProspectDetail,
  readProspects,
  prospectConversationLink,
} from "../../lib/leads";
import { callAuthenticatedBackend } from "../../lib/api";
vi.mock("../../lib/api", () => ({ callAuthenticatedBackend: vi.fn() }));
const tenant = "019c2000-0000-7000-8000-000000000102";
const identity = "019c2000-0000-7000-8000-000000000601";
const conversation = "019c2000-0000-7000-8000-000000000303";
const prospect = {
  id: identity,
  tenant_id: tenant,
  contact_name: "<script>ejemplo</script>",
  contact_username: null,
  phone_number: "+573000000001",
  declared_company: null,
  service_interests: ["Agente de ventas"],
  need_summary: "Atender clientes",
  status: "NEW",
  capture_suppressed: false,
  identity_conflict: false,
  first_conversation_id: conversation,
  last_conversation_id: conversation,
  created_at: "2026-10-19T10:00:00Z",
  updated_at: "2026-10-19T10:00:00Z",
};
it("keeps missing data empty and validates every row's tenant", () => {
  expect(
    parseProspectPage({ items: [prospect], next_cursor: null }, tenant).items[0]
      .declared_company,
  ).toBeNull();
  expect(() =>
    parseProspectPage(
      { items: [{ ...prospect, tenant_id: identity }], next_cursor: null },
      tenant,
    ),
  ).toThrow();
  expect(() =>
    parseProspectPage(
      { items: Array(21).fill(prospect), next_cursor: null },
      tenant,
    ),
  ).toThrow();
});
it("validates selected identity and source pagination instead of returning a fake empty detail", () => {
  const detail = { prospect, events: { items: [], next_cursor: null } };
  expect(
    parseProspectDetail(detail, tenant, identity).prospect.contact_name,
  ).toBe("<script>ejemplo</script>");
  expect(() => parseProspectDetail(detail, tenant, conversation)).toThrow();
  expect(() =>
    parseProspectDetail({ prospect, events: null }, tenant, identity),
  ).toThrow();
});
it("never hides transport failures as an empty prospect page", async () => {
  vi.mocked(callAuthenticatedBackend).mockRejectedValueOnce(
    new Error("unavailable"),
  );
  await expect(readProspects(tenant, {})).rejects.toThrow("unavailable");
  await expect(readProspects("../other", {})).rejects.toThrow();
});
it("links back to the exact tenant and source conversation", () => {
  expect(prospectConversationLink(tenant, conversation)).toBe(
    `/conversation-log?tenant=${tenant}&conversation=${conversation}`,
  );
  expect(() => prospectConversationLink(tenant, "unsafe?admin=true")).toThrow();
});
it("preserves more than one hundred valid interests accepted by persistence", () => {
  const interests = Array.from({ length: 101 }, (_, i) => `Necesidad ${i}`);
  const value = { ...prospect, service_interests: interests };
  expect(
    parseProspectPage({ items: [value], next_cursor: null }, tenant).items[0]
      .service_interests,
  ).toEqual(interests);
  expect(
    parseProspectDetail(
      { prospect: value, events: { items: [], next_cursor: null } },
      tenant,
      identity,
    ).prospect.service_interests,
  ).toEqual(interests);
});
