import { resumeCoexistenceConversation } from "../../../../actions";

export type HumanConversation = {
  conversation_id: string;
  customer_hint: string;
  state_version: number;
};

export function HumanControl({
  tenantId,
  accountId,
  conversations,
}: {
  tenantId: string;
  accountId: string;
  conversations: HumanConversation[] | null;
}) {
  return (
    <section className="human-control" aria-label="Control humano">
      <h3>Conversaciones en atención humana</h3>
      <p>
        Mientras una persona atiende, el agente no responde en esa conversación.
        Se muestran hasta 20 conversaciones recientes.
      </p>
      {conversations === null ? (
        <p role="status">No se pudo consultar el control de conversaciones.</p>
      ) : conversations.length === 0 ? (
        <p>No hay conversaciones bajo control humano en esta cuenta.</p>
      ) : (
        <ul className="human-control-list">
          {conversations.map((conversation) => (
            <li key={conversation.conversation_id}>
              <div>
                <strong>Cliente {conversation.customer_hint}</strong>
                <small>
                  Referencia {conversation.conversation_id.slice(0, 8)}
                </small>
              </div>
              <details>
                <summary>Reactivar agente</summary>
                <p>
                  El agente podrá responder a futuros mensajes. Esta acción no
                  envía una respuesta inmediata.
                </p>
                <form action={resumeCoexistenceConversation}>
                  <input type="hidden" name="tenantId" value={tenantId} />
                  <input type="hidden" name="accountId" value={accountId} />
                  <input type="hidden" name="confirmed" value="resume" />
                  <input
                    type="hidden"
                    name="conversationId"
                    value={conversation.conversation_id}
                  />
                  <input
                    type="hidden"
                    name="expectedVersion"
                    value={conversation.state_version}
                  />
                  <button type="submit">Confirmar reactivación</button>
                </form>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
