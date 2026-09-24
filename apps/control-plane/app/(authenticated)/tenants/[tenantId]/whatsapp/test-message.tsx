"use client";

import { useRef, useState } from "react";
import {
  getWhatsAppTestStatus,
  loadWhatsAppTestTemplates,
  sendWhatsAppTest,
} from "../../../../actions";

const labels: Record<string, string> = {
  PREPARED: "En cola de envío",
  SENDING: "Enviando",
  ACCEPTED: "Aceptado por Meta",
  SENT: "Enviado",
  DELIVERED: "Entregado",
  READ: "Leído",
  FAILED: "Falló el envío",
  BLOCKED: "Envío bloqueado",
  UNCERTAIN: "Resultado pendiente de confirmar; no repitas el envío",
};

export function TestMessage({
  tenantId,
  accountId,
}: {
  tenantId: string;
  accountId: string;
}) {
  const [templates, setTemplates] = useState<
    { name: string; language: string }[]
  >([]);
  const [selected, setSelected] = useState("0");
  const [recipient, setRecipient] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ id: string; status: string } | null>(
    null,
  );
  const attempt = useRef<string | null>(null);
  const locked = useRef(false);

  async function run(operation: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setNotice("");
    try {
      await operation();
    } catch {
      setNotice("No se pudo completar la solicitud. Vuelve a intentarlo.");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  return (
    <section className="setup-panel" aria-label="Enviar mensaje de prueba">
      <div style={{ display: "grid", gap: "1rem", width: "100%" }}>
        <h2>Enviar mensaje de prueba</h2>
        <p>
          Envía una plantilla de esta cuenta a tu propio WhatsApp. Si usas el
          número de prueba de Meta, registra primero tu celular como
          destinatario en Meta.
        </p>
        <button
          type="button"
          disabled={busy || !!message}
          onClick={() =>
            void run(async () => {
              const result = await loadWhatsAppTestTemplates(
                tenantId,
                accountId,
              );
              if (!result.ok) {
                setNotice(result.message);
                return;
              }
              setTemplates(result.data);
              setSelected("0");
              if (!result.data.length)
                setNotice(
                  "No se encontraron plantillas aprobadas de texto sin variables entre las primeras 100. Crea una en Meta y vuelve a cargar.",
                );
            })
          }
        >
          Cargar plantillas desde Meta
        </button>
        <form
          style={{ display: "grid", gap: "1rem" }}
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              const template = templates[Number(selected)];
              if (!template || message) return;
              attempt.current ??= crypto.randomUUID();
              const result = await sendWhatsAppTest({
                tenantId,
                accountId,
                recipient: recipient.replace(/[+\s()-]/g, ""),
                templateName: template.name,
                language: template.language,
                idempotencyKey: attempt.current,
              });
              if (!result.ok) {
                setNotice(result.message);
                return;
              }
              setMessage(result.data);
            });
          }}
        >
          <label>
            Plantilla aprobada
            <select
              value={selected}
              disabled={busy || !!message}
              onChange={(e) => {
                setSelected(e.target.value);
                attempt.current = null;
              }}
              required
            >
              {!templates.length && (
                <option value="">Carga las plantillas primero</option>
              )}
              {templates.map((t, i) => (
                <option key={`${t.name}:${t.language}`} value={i}>
                  {t.name} · {t.language}
                </option>
              ))}
            </select>
          </label>
          <label>
            Tu número con código de país
            <input
              type="tel"
              value={recipient}
              onChange={(e) => {
                setRecipient(e.target.value);
                attempt.current = null;
              }}
              placeholder="+57 300 123 4567"
              required
              maxLength={25}
              disabled={busy || !!message}
            />
          </label>
          <button
            type="submit"
            disabled={busy || !!message || !templates.length}
          >
            Enviar mensaje de prueba
          </button>
        </form>
        {notice && <p role="alert">{notice}</p>}
        {message && (
          <div>
            <p role="status">{labels[message.status] ?? message.status}</p>
            <p>Referencia: {message.id}</p>
            <p>
              “Aceptado por Meta” no confirma la entrega. Comprueba el mensaje
              en WhatsApp; los estados de entrega necesitan el webhook
              configurado.
            </p>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const result = await getWhatsAppTestStatus(
                    tenantId,
                    accountId,
                    message.id,
                  );
                  if (result.ok) setMessage(result.data);
                  else setNotice(result.message);
                })
              }
            >
              Actualizar estado
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
