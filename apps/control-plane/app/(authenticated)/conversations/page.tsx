import Link from "next/link";
import { AudioTranscription } from "../../../components/audio-transcription";
import {
  validAudioFields,
  type AudioReadFields,
} from "../../../lib/audio-transcription";
import { callAuthenticatedBackend } from "../../../lib/api";
import {
  contactTitle,
  contactDetails,
  validContactIdentity,
  type ContactIdentity,
} from "../../../lib/contact-identity";

type Query = {
  tenant?: string;
  conversation?: string;
  offset?: string;
  messagesOffset?: string;
};
type Tenant = { id: string; name: string };
type Conversation = ContactIdentity & {
  id: string;
  customer_wa_id: string;
  control_state: string;
  updated_at: string;
};
type Message = AudioReadFields & {
  id: string;
  direction: string;
  message_type: string;
  text: string | null;
  created_at: string;
};
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const states: Record<string, string> = {
  AI_ACTIVE: "Control del agente",
  HUMAN_ACTIVE: "Atención humana",
  AWAITING_HUMAN: "Esperando atención humana",
  CLOSED: "Cerrada",
};
function offset(value?: string) {
  return value && /^\d+$/.test(value) && Number(value) <= 1_000_000
    ? Number(value)
    : 0;
}
function date(value: string) {
  return new Date(value).toLocaleString("es-CO", {
    timeZone: "America/Bogota",
  });
}
function records(value: unknown): value is Record<string, unknown>[] {
  return (
    Array.isArray(value) &&
    value.every(
      (row) => row !== null && typeof row === "object" && !Array.isArray(row),
    )
  );
}
function validDate(value: unknown) {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

export default async function ConversationsPage({
  searchParams,
}: {
  searchParams?: Promise<Query>;
}) {
  const query = (await searchParams) ?? {};
  const start = offset(query.offset),
    messagesStart = offset(query.messagesOffset);
  let tenants: Tenant[] = [],
    conversations: Conversation[] | null = null,
    messages: Message[] | null = null;
  let selected: Tenant | undefined;
  let error = false,
    messageError = false;
  try {
    const result = await callAuthenticatedBackend<unknown>("/admin/tenants");
    if (
      !records(result) ||
      !result.every(
        (row) =>
          typeof row.id === "string" &&
          uuid.test(row.id) &&
          typeof row.name === "string",
      )
    )
      throw new Error("Invalid data");
    tenants = result as Tenant[];
    selected = query.tenant
      ? tenants.find((tenant) => tenant.id === query.tenant)
      : tenants[0];
    if (query.tenant && !selected) throw new Error("Unknown tenant");
    if (selected) {
      const result = await callAuthenticatedBackend<unknown>(
        `/admin/tenants/${selected.id}/conversations?limit=50&offset=${start}`,
      );
      if (
        !records(result) ||
        result.length > 50 ||
        !result.every(
          (row) =>
            typeof row.id === "string" &&
            uuid.test(row.id) &&
            typeof row.customer_wa_id === "string" &&
            validContactIdentity(row) &&
            typeof row.control_state === "string" &&
            Object.hasOwn(states, row.control_state) &&
            validDate(row.updated_at),
        )
      )
        throw new Error("Invalid data");
      conversations = result as Conversation[];
    }
  } catch {
    error = true;
  }
  const chosen = conversations?.find((row) => row.id === query.conversation);
  if (selected && chosen) {
    try {
      const result = await callAuthenticatedBackend<unknown>(
        `/admin/tenants/${selected.id}/conversations/${chosen.id}/messages?limit=50&offset=${messagesStart}`,
      );
      if (
        !records(result) ||
        result.length > 50 ||
        !result.every(
          (row) =>
            typeof row.id === "string" &&
            uuid.test(row.id) &&
            ["inbound", "outbound", "system"].includes(String(row.direction)) &&
            typeof row.message_type === "string" &&
            validAudioFields(row) &&
            (row.text === null || typeof row.text === "string") &&
            validDate(row.created_at),
        )
      )
        throw new Error("Invalid data");
      messages = result as Message[];
    } catch {
      messageError = true;
    }
  }
  const base = selected
    ? `/conversations?tenant=${selected.id}`
    : "/conversations";
  return (
    <main className="workspace-page">
      <p className="eyebrow">CONTROL PLANE</p>
      <h1>Conversations</h1>
      <p className="workspace-description">
        Conversaciones y mensajes registrados. Vista de solo lectura.
      </p>
      <nav aria-label="Clientes">
        <ul>
          {tenants.map((tenant) => (
            <li key={tenant.id}>
              <Link
                href={`/conversations?tenant=${tenant.id}`}
                aria-current={tenant.id === selected?.id ? "page" : undefined}
              >
                {tenant.name}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <Link
        href={`${base}${selected ? "&" : "?"}offset=${start}`}
        className="button-link"
      >
        Actualizar conversaciones
      </Link>
      {error ? (
        <p role="alert">
          No se pudieron consultar las conversaciones. Intenta actualizar la
          página.
        </p>
      ) : !selected ? (
        <p>No hay clientes disponibles.</p>
      ) : (
        <>
          <h2>{selected.name}</h2>
          {conversations?.length === 0 ? (
            <p>No hay conversaciones registradas para este cliente.</p>
          ) : (
            <div className="tenant-grid">
              {conversations?.map((row) => (
                <article className="tenant-card" key={row.id}>
                  <div>
                    <h3>{contactTitle(row)}</h3>
                    <p>{contactDetails(row)}</p>
                    <p>{states[row.control_state]}</p>
                    <p>Actualizada: {date(row.updated_at)}</p>
                  </div>
                  <Link
                    className="button-link"
                    href={`${base}&offset=${start}&conversation=${row.id}`}
                  >
                    Ver mensajes
                  </Link>
                </article>
              ))}
            </div>
          )}
          <nav aria-label="Páginas de conversaciones">
            {start > 0 && (
              <Link href={`${base}&offset=${Math.max(0, start - 50)}`}>
                Anteriores
              </Link>
            )}{" "}
            {conversations?.length === 50 && (
              <Link href={`${base}&offset=${start + 50}`}>Siguientes</Link>
            )}
          </nav>
          {query.conversation && !chosen ? (
            <p role="status">
              Selecciona una conversación de esta página para ver sus mensajes.
            </p>
          ) : null}
          {chosen && (
            <section aria-label="Mensajes">
              <h2>Mensajes de {contactTitle(chosen)}</h2>
              <p>{contactDetails(chosen)}</p>
              {messageError ? (
                <p role="alert">No se pudieron consultar los mensajes.</p>
              ) : (
                <>
                  <p>Hasta 50 mensajes por página, en orden de llegada.</p>
                  {messages?.length === 0 ? (
                    <p>No hay mensajes registrados.</p>
                  ) : (
                    <ol>
                      {messages?.map((message) => (
                        <li key={message.id}>
                          <strong>
                            {message.direction === "inbound"
                              ? "Contacto"
                              : message.direction === "outbound"
                                ? "Salida"
                                : "Sistema"}
                          </strong>{" "}
                          · {date(message.created_at)}
                          {message.message_type === "audio" ? (
                            <AudioTranscription
                              state={message.audio_state}
                              text={message.text}
                            />
                          ) : (
                            <p
                              style={{
                                whiteSpace: "pre-wrap",
                                overflowWrap: "anywhere",
                              }}
                            >
                              {message.text ??
                                `Mensaje de tipo ${message.message_type}. Vista multimedia no disponible.`}
                            </p>
                          )}
                        </li>
                      ))}
                    </ol>
                  )}
                  <nav aria-label="Páginas de mensajes">
                    {messagesStart > 0 && (
                      <Link
                        href={`${base}&offset=${start}&conversation=${chosen.id}&messagesOffset=${Math.max(0, messagesStart - 50)}`}
                      >
                        Más recientes
                      </Link>
                    )}{" "}
                    {messages?.length === 50 && (
                      <Link
                        href={`${base}&offset=${start}&conversation=${chosen.id}&messagesOffset=${messagesStart + 50}`}
                      >
                        Más antiguos
                      </Link>
                    )}
                  </nav>
                </>
              )}
            </section>
          )}
        </>
      )}
    </main>
  );
}
