import "server-only";
import { callAuthenticatedBackend } from "./api";
import { isWorkspaceId } from "./agent-workspace";
import { validContactIdentity, type ContactIdentity } from "./contact-identity";
import { validAudioFields, type AudioReadFields } from "./audio-transcription";
export type ConversationRow = ContactIdentity & {
  id: string;
  account_id: string;
  customer_wa_id: string;
  control_state: string;
  updated_at: string;
  last_activity_at?: string;
  agent_ids: string[];
};
export type MessageRow = AudioReadFields & {
  id: string;
  arrival_sequence: number;
  direction: string;
  message_type: string;
  text: string | null;
  created_at: string;
  agent_id: string | null;
  agent_spec_id: string | null;
  delivery_status: string | null;
};
export type ReadPage<T> = { items: T[]; next_cursor: string | null };
const record = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const id = (v: unknown): v is string =>
  typeof v === "string" && isWorkspaceId(v);
const date = (v: unknown) =>
  typeof v === "string" && Number.isFinite(Date.parse(v));
const delivery = [
  "PREPARED",
  "SENDING",
  "ACCEPTED",
  "SENT",
  "DELIVERED",
  "READ",
  "FAILED",
  "UNCERTAIN",
  "BLOCKED",
];
export const controlLabels: Record<string, string> = {
  AI_ACTIVE: "Control del agente",
  HUMAN_ACTIVE: "Atención humana",
  AWAITING_HUMAN: "Esperando atención humana",
  CLOSED: "Cerrada",
};
export const deliveryLabels: Record<string, string> = {
  PREPARED: "Preparado",
  SENDING: "Enviando",
  ACCEPTED: "Aceptado por Meta",
  SENT: "Enviado",
  DELIVERED: "Entregado",
  READ: "Leído",
  FAILED: "Fallido",
  UNCERTAIN: "Entrega sin confirmar",
  BLOCKED: "Bloqueado",
};
function page<T>(v: unknown, check: (item: unknown) => item is T): ReadPage<T> {
  if (
    !record(v) ||
    !Array.isArray(v.items) ||
    v.items.length > 20 ||
    !v.items.every(check) ||
    (v.next_cursor !== null && typeof v.next_cursor !== "string")
  )
    throw new Error("Invalid conversation data");
  return { items: v.items, next_cursor: v.next_cursor as string | null };
}
function isConversation(r: unknown): r is ConversationRow {
  return (
    record(r) &&
    id(r.id) &&
    id(r.account_id) &&
    typeof r.customer_wa_id === "string" &&
    validContactIdentity(r) &&
    typeof r.control_state === "string" &&
    Object.hasOwn(controlLabels, r.control_state) &&
    date(r.updated_at) &&
    (r.last_activity_at === undefined || date(r.last_activity_at)) &&
    Array.isArray(r.agent_ids) &&
    r.agent_ids.every(id)
  );
}
export async function readConversations(
  tenant: string,
  filters: { agent?: string; account?: string; cursor?: string },
): Promise<ReadPage<ConversationRow>> {
  if (
    !isWorkspaceId(tenant) ||
    [filters.agent, filters.account].some((v) => v && !isWorkspaceId(v))
  )
    throw new Error("Invalid conversation scope");
  const query = new URLSearchParams();
  if (filters.agent) query.set("agent_id", filters.agent);
  if (filters.account) query.set("account_id", filters.account);
  if (filters.cursor) query.set("cursor", filters.cursor);
  return page(
    await callAuthenticatedBackend(
      `/admin/agent-workspace/companies/${tenant}/conversations${query.size ? `?${query}` : ""}`,
    ),
    isConversation,
  );
}
export async function readConversation(
  tenant: string,
  conversation: string,
  filters: { agent?: string; account?: string },
): Promise<ConversationRow> {
  if (
    !isWorkspaceId(tenant) ||
    !isWorkspaceId(conversation) ||
    [filters.agent, filters.account].some((v) => v && !isWorkspaceId(v))
  )
    throw new Error("Invalid scope");
  const query = new URLSearchParams();
  if (filters.agent) query.set("agent_id", filters.agent);
  if (filters.account) query.set("account_id", filters.account);
  const value = await callAuthenticatedBackend(
    `/admin/agent-workspace/companies/${tenant}/conversations/${conversation}${query.size ? `?${query}` : ""}`,
  );
  if (!isConversation(value) || value.id !== conversation)
    throw new Error("Invalid selected conversation");
  return value;
}
export async function readMessages(
  tenant: string,
  conversation: string,
  cursor?: string,
): Promise<ReadPage<MessageRow>> {
  if (!isWorkspaceId(tenant) || !isWorkspaceId(conversation))
    throw new Error("Invalid conversation scope");
  return page(
    await callAuthenticatedBackend(
      `/admin/agent-workspace/companies/${tenant}/conversations/${conversation}/messages${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
    ),
    (r): r is MessageRow =>
      record(r) &&
      id(r.id) &&
      typeof r.arrival_sequence === "number" &&
      ["inbound", "outbound", "system"].includes(String(r.direction)) &&
      typeof r.message_type === "string" &&
      validAudioFields(r) &&
      (r.text === null || typeof r.text === "string") &&
      date(r.created_at) &&
      (r.agent_id === null || id(r.agent_id)) &&
      (r.agent_spec_id === null || id(r.agent_spec_id)) &&
      (r.delivery_status === null ||
        delivery.includes(String(r.delivery_status))),
  );
}
