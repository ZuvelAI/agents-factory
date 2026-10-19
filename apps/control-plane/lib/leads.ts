import "server-only";
import { callAuthenticatedBackend } from "./api";
import { isWorkspaceId } from "./agent-workspace";

export type Prospect = {
  id: string;
  tenant_id: string;
  contact_name: string | null;
  contact_username: string | null;
  phone_number: string | null;
  declared_company: string | null;
  service_interests: string[];
  need_summary: string | null;
  status: "NEW";
  capture_suppressed: boolean;
  identity_conflict: boolean;
  first_conversation_id: string;
  last_conversation_id: string;
  created_at: string;
  updated_at: string;
};
export type ProspectEvent = {
  id: string;
  conversation_id: string;
  inbound_message_id: string;
  agent_instance_id: string;
  agent_version_id: string;
  agent_name: string | null;
  version_number: number;
  operation: "CAPTURE" | "SUPPRESS" | "CONFLICT";
  evidence: { message_id: string; quote: string }[];
  created_at: string;
};
export type LeadPage<T> = { items: T[]; next_cursor: string | null };
export type ProspectDetail = {
  prospect: Prospect;
  events: LeadPage<ProspectEvent>;
};
const record = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const id = (v: unknown): v is string =>
  typeof v === "string" && isWorkspaceId(v);
const text = (v: unknown) =>
  v === null || (typeof v === "string" && v.length <= 2000);
const date = (v: unknown) =>
  typeof v === "string" && Number.isFinite(Date.parse(v));
function isProspect(v: unknown, tenant: string): v is Prospect {
  return (
    record(v) &&
    id(v.id) &&
    v.tenant_id === tenant &&
    [
      v.contact_name,
      v.contact_username,
      v.declared_company,
      v.need_summary,
    ].every(text) &&
    (v.phone_number === null ||
      (typeof v.phone_number === "string" &&
        /^\+[1-9]\d{6,14}$/.test(v.phone_number))) &&
    Array.isArray(v.service_interests) &&
    v.service_interests.every(
      (s) => typeof s === "string" && s.length <= 300,
    ) &&
    v.status === "NEW" &&
    typeof v.capture_suppressed === "boolean" &&
    typeof v.identity_conflict === "boolean" &&
    id(v.first_conversation_id) &&
    id(v.last_conversation_id) &&
    date(v.created_at) &&
    date(v.updated_at)
  );
}
function isEvent(v: unknown): v is ProspectEvent {
  return (
    record(v) &&
    [
      v.id,
      v.conversation_id,
      v.inbound_message_id,
      v.agent_instance_id,
      v.agent_version_id,
    ].every(id) &&
    text(v.agent_name) &&
    Number.isSafeInteger(v.version_number) &&
    Number(v.version_number) > 0 &&
    ["CAPTURE", "SUPPRESS", "CONFLICT"].includes(String(v.operation)) &&
    date(v.created_at) &&
    Array.isArray(v.evidence) &&
    v.evidence.length <= 5 &&
    v.evidence.every(
      (e) =>
        record(e) &&
        id(e.message_id) &&
        typeof e.quote === "string" &&
        e.quote.length <= 500,
    )
  );
}
function page<T>(v: unknown, check: (v: unknown) => v is T): LeadPage<T> {
  if (
    !record(v) ||
    !Array.isArray(v.items) ||
    v.items.length > 20 ||
    !v.items.every(check) ||
    !(
      v.next_cursor === null ||
      (typeof v.next_cursor === "string" && v.next_cursor.length <= 512)
    )
  )
    throw new Error("Invalid prospect response");
  return { items: v.items, next_cursor: v.next_cursor as string | null };
}
export function parseProspectPage(v: unknown, tenant: string) {
  if (!id(tenant)) throw new Error("Invalid company");
  return page(v, (item): item is Prospect => isProspect(item, tenant));
}
export function parseProspectDetail(
  v: unknown,
  tenant: string,
  prospect: string,
): ProspectDetail {
  if (
    !record(v) ||
    !isProspect(v.prospect, tenant) ||
    v.prospect.id !== prospect
  )
    throw new Error("Invalid prospect detail");
  return { prospect: v.prospect, events: page(v.events, isEvent) };
}
function root(tenant: string) {
  if (!id(tenant)) throw new Error("Invalid company");
  return `/admin/agent-workspace/companies/${tenant}`;
}
export async function readProspects(
  tenant: string,
  query: { agent?: string; q?: string; cursor?: string },
) {
  const path = root(tenant),
    params = new URLSearchParams();
  if (query.agent) {
    if (!id(query.agent)) throw new Error("Invalid agent");
    params.set("agent_id", query.agent);
  }
  if (query.q) {
    if (query.q.length > 200) throw new Error("Invalid search");
    params.set("q", query.q);
  }
  if (query.cursor) params.set("cursor", query.cursor);
  return parseProspectPage(
    await callAuthenticatedBackend(`${path}/prospects?${params}`),
    tenant,
  );
}
export async function readProspect(
  tenant: string,
  prospect: string,
  agent?: string,
) {
  if (!id(prospect) || (agent && !id(agent)))
    throw new Error("Invalid prospect");
  return parseProspectDetail(
    await callAuthenticatedBackend(
      `${root(tenant)}/prospects/${prospect}${agent ? `?agent_id=${agent}` : ""}`,
    ),
    tenant,
    prospect,
  );
}
export async function readProspectEvents(
  tenant: string,
  prospect: string,
  cursor: string,
) {
  if (!id(prospect)) throw new Error("Invalid prospect");
  return page(
    await callAuthenticatedBackend(
      `${root(tenant)}/prospects/${prospect}/events?cursor=${encodeURIComponent(cursor)}`,
    ),
    isEvent,
  );
}
export async function readConversationProspect(
  tenant: string,
  conversation: string,
) {
  if (!id(conversation)) throw new Error("Invalid conversation");
  const v = await callAuthenticatedBackend(
    `${root(tenant)}/conversations/${conversation}/prospect`,
  );
  if (v === null) return null;
  if (!isProspect(v, tenant)) throw new Error("Invalid related prospect");
  return v;
}
export function prospectConversationLink(tenant: string, conversation: string) {
  root(tenant);
  if (!id(conversation)) throw new Error("Invalid conversation");
  return `/conversation-log?tenant=${tenant}&conversation=${conversation}`;
}
export const prospectName = (p: Prospect) =>
  p.contact_name ||
  p.phone_number ||
  p.contact_username ||
  "Contacto sin nombre";
