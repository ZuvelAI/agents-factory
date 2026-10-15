import Link from "next/link";
import {
  isWorkspaceId,
  readAgents,
  readCompanies,
} from "../../../lib/agent-workspace";
import {
  readConversations,
  readMessages,
  controlLabels,
  deliveryLabels,
  type ReadPage,
  type MessageRow,
} from "../../../lib/conversation-workspace";
import { ConversationRefresh } from "../../../components/agent-workspace/conversation-refresh";
import { ConversationFilters } from "../../../components/agent-workspace/conversation-filters";
type Query = {
  tenant?: string;
  agent?: string;
  account?: string;
  conversation?: string;
  cursor?: string;
  messagesCursor?: string;
};
const date = (value: string) =>
  new Date(value).toLocaleString("es-CO", { timeZone: "America/Bogota" });
export default async function ConversationLog({
  searchParams,
}: {
  searchParams?: Promise<Query>;
}) {
  const query = (await searchParams) ?? {};
  let companies: Awaited<ReturnType<typeof readCompanies>>;
  let agents: Awaited<ReturnType<typeof readAgents>> | undefined;
  let conversations: Awaited<ReturnType<typeof readConversations>> | undefined;
  let tenant: string | undefined;
  let name: string | undefined;
  try {
    for (const value of [
      query.tenant,
      query.agent,
      query.account,
      query.conversation,
    ])
      if (value && !isWorkspaceId(value)) throw new Error("Invalid scope");
    companies = await readCompanies();
    tenant = query.tenant ?? companies.items[0]?.id;
    if (tenant) {
      agents = await readAgents(tenant);
      name =
        agents.company_name ??
        companies.items.find((c) => c.id === tenant)?.name ??
        "Empresa seleccionada";
      conversations = await readConversations(tenant, query);
    }
  } catch {
    return (
      <section className="workspace">
        <h1>Conversaciones</h1>
        <div className="workspace-empty" role="alert">
          <h2>No pudimos consultar las conversaciones</h2>
          <p>No se ha modificado ninguna conversación.</p>
          <Link href="/conversation-log">Volver a consultar</Link>
        </div>
      </section>
    );
  }
  if (!tenant || !conversations || !agents)
    return (
      <section className="workspace">
        <h1>Conversaciones</h1>
        <p>No hay empresas disponibles.</p>
        <Link href="/tenants">Ver empresas</Link>
      </section>
    );
  const chosen = conversations.items.find((c) => c.id === query.conversation);
  let messages: ReadPage<MessageRow> | null = null,
    messageError = false;
  if (chosen) {
    try {
      messages = await readMessages(tenant, chosen.id, query.messagesCursor);
    } catch {
      messageError = true;
    }
  }
  function link(extra: Partial<Query> = {}) {
    const merged = { ...query, tenant, ...extra };
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(merged))
      if (value) params.set(key, value);
    return `/conversation-log?${params}`;
  }
  const accountOptions = new Map(
    agents.items.flatMap((a) =>
      a.channel_accounts.map(
        (c) =>
          [
            c.account_id,
            c.display_number ?? "Cuenta sin número visible",
          ] as const,
      ),
    ),
  );
  if (query.account && !accountOptions.has(query.account))
    accountOptions.set(query.account, "Cuenta seleccionada");
  return (
    <section className="workspace">
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">Conversaciones por empresa y agente</p>
          <h1>Conversaciones</h1>
          <p className="workspace-muted">
            {name} · Mensajes operativos registrados, sin modificar su
            historial.
          </p>
        </div>
        <Link className="workspace-secondary" href={link()}>
          Actualizar
        </Link>
      </header>
      <ConversationFilters>
        <div>
          <label htmlFor="conversation-company">Empresa</label>
          <select id="conversation-company" name="tenant" defaultValue={tenant}>
            {companies.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
            {!companies.items.some((c) => c.id === tenant) ? (
              <option value={tenant}>{name}</option>
            ) : null}
          </select>
        </div>
        <div>
          <label htmlFor="conversation-agent">Agente</label>
          <select
            id="conversation-agent"
            name="agent"
            defaultValue={query.agent ?? ""}
          >
            <option value="">Todos los agentes</option>
            {agents.items.map((a) => (
              <option key={a.id} value={a.id}>
                {a.display_name}
              </option>
            ))}
            {query.agent && !agents.items.some((a) => a.id === query.agent) ? (
              <option value={query.agent}>Agente seleccionado</option>
            ) : null}
          </select>
        </div>
        <div>
          <label htmlFor="conversation-account">Cuenta</label>
          <select
            id="conversation-account"
            name="account"
            defaultValue={query.account ?? ""}
          >
            <option value="">Todas las cuentas</option>
            {Array.from(accountOptions, ([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className="workspace-secondary">
          Aplicar filtros
        </button>
        <Link href={`/conversation-log?tenant=${tenant}`}>Limpiar filtros</Link>
      </ConversationFilters>
      <p className="workspace-muted">
        Los filtros de agente incluyen conversaciones con respuestas atribuidas
        a ese agente. El historial importado de WhatsApp se conserva por
        separado; no se atribuye automáticamente al agente actual.
      </p>
      <ConversationRefresh />
      <div className="workspace-inbox">
        <aside className="workspace-card workspace-inbox-list">
          <h2>Conversaciones</h2>
          {conversations.items.length ? (
            conversations.items.map((row) => (
              <Link
                className={`workspace-thread ${chosen?.id === row.id ? "workspace-thread-selected" : ""}`}
                key={row.id}
                href={link({ conversation: row.id, messagesCursor: undefined })}
              >
                <strong>{row.customer_wa_id}</strong>
                <span>{controlLabels[row.control_state]}</span>
                <small>{date(row.updated_at)}</small>
                <small>
                  {row.agent_ids.length
                    ? `${row.agent_ids.length} agente(s) con respuestas registradas`
                    : "Agente no identificado en el historial"}
                </small>
              </Link>
            ))
          ) : (
            <p>No hay conversaciones para estos filtros.</p>
          )}
          {conversations.next_cursor ? (
            <Link
              href={link({
                cursor: conversations.next_cursor,
                conversation: undefined,
                messagesCursor: undefined,
              })}
            >
              Más conversaciones →
            </Link>
          ) : null}
          {query.cursor ? (
            <Link
              href={link({
                cursor: undefined,
                conversation: undefined,
                messagesCursor: undefined,
              })}
            >
              Primera página
            </Link>
          ) : null}
        </aside>
        <article
          className="workspace-card workspace-chat"
          aria-label="Mensajes"
        >
          {!chosen ? (
            <>
              <h2>Selecciona una conversación</h2>
              <p className="workspace-muted">
                Abre un contacto para ver mensajes, contexto y estado de
                entrega. Esta vista es de solo lectura.
              </p>
            </>
          ) : (
            <>
              <h2>{chosen.customer_wa_id}</h2>
              <p className="workspace-muted">
                {controlLabels[chosen.control_state]} · Cuenta{" "}
                {chosen.account_id}
              </p>
              {messageError ? (
                <p role="alert">No pudimos consultar los mensajes.</p>
              ) : (
                <>
                  {messages?.next_cursor ? (
                    <Link href={link({ messagesCursor: messages.next_cursor })}>
                      Mensajes anteriores
                    </Link>
                  ) : null}
                  {query.messagesCursor ? (
                    <Link href={link({ messagesCursor: undefined })}>
                      Volver a los recientes
                    </Link>
                  ) : null}
                  <ol className="workspace-messages">
                    {messages?.items.map((message) => (
                      <li
                        className={`workspace-message workspace-message-${message.direction}`}
                        key={message.id}
                      >
                        <div>
                          <strong>
                            {message.direction === "inbound"
                              ? "Contacto"
                              : message.direction === "outbound"
                                ? "Salida"
                                : "Sistema"}
                          </strong>
                          <time dateTime={message.created_at}>
                            {date(message.created_at)}
                          </time>
                        </div>
                        <p>
                          {message.text ??
                            `Mensaje ${message.message_type}; vista multimedia no disponible.`}
                        </p>
                        <small>
                          {message.agent_id
                            ? `Agente ${message.agent_id}`
                            : "Atribución de agente no disponible"}
                          {message.agent_spec_id
                            ? ` · Versión registrada ${message.agent_spec_id}`
                            : ""}
                        </small>
                        {message.delivery_status ? (
                          <small>
                            {deliveryLabels[message.delivery_status]}
                          </small>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                  {messages?.items.length === 0 ? (
                    <p>No hay mensajes registrados.</p>
                  ) : null}
                </>
              )}
            </>
          )}
        </article>
      </div>
    </section>
  );
}
