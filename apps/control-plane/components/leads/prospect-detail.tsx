import Link from "next/link";
import {
  prospectName,
  prospectConversationLink,
  type ProspectDetail as Detail,
} from "../../lib/leads";
import styles from "./prospects.module.css";
export function ProspectDetail({
  detail,
  tenant,
  nextEvents,
}: {
  detail: Detail;
  tenant: string;
  nextEvents?: string;
}) {
  const p = detail.prospect;
  return (
    <section className={styles.panel} aria-label="Detalle del prospecto">
      <div className={styles.detail}>
        <div className={styles.panelHeading}>
          <span className={styles.muted}>Detalle del prospecto</span>
          <span className={styles.badge}>Nuevo</span>
        </div>
        <div className={styles.identity}>
          <span className={styles.avatar} aria-hidden="true">
            {prospectName(p).slice(0, 1).toUpperCase()}
          </span>
          <div>
            <h2>{prospectName(p)}</h2>
            <p className={styles.muted}>
              {p.declared_company || "Empresa sin indicar"}
            </p>
          </div>
        </div>
        {p.identity_conflict ? (
          <p className={styles.warning} role="status">
            Identidad en conflicto. No se han fusionado los contactos; revisa
            las fuentes antes de utilizar estos datos.
          </p>
        ) : null}
        {p.capture_suppressed ? (
          <p className={styles.warning} role="status">
            Captura detenida por solicitud del contacto. No se añadirán nuevos
            datos comerciales.
          </p>
        ) : null}
        <dl className={styles.fields}>
          <div>
            <dt>Teléfono</dt>
            <dd>{p.phone_number || "No disponible"}</dd>
          </div>
          <div>
            <dt>Usuario</dt>
            <dd>{p.contact_username || "No disponible"}</dd>
          </div>
          <div>
            <dt>Empresa declarada</dt>
            <dd>{p.declared_company || "Sin indicar"}</dd>
          </div>
          <div>
            <dt>Intereses</dt>
            <dd>{p.service_interests.join(" · ") || "Sin especificar"}</dd>
          </div>
        </dl>
        <div className={styles.need}>
          <h3>¿Qué necesita?</h3>
          <p>
            {p.need_summary || "Todavía no hay un resumen de la necesidad."}
          </p>
        </div>
        <Link
          className="workspace-primary"
          href={prospectConversationLink(tenant, p.first_conversation_id)}
        >
          Ver conversación
        </Link>
        <div className={styles.sources}>
          <h3>Fuentes y evidencia</h3>
          <p className={styles.muted}>
            Datos extraídos de mensajes del contacto; no verificados de forma
            independiente.
          </p>
          {detail.events.items.map((e) => (
            <article key={e.id} className={styles.source}>
              <p>
                <strong>
                  {e.agent_name || "Agente sin nombre registrado"}
                </strong>{" "}
                · Versión {e.version_number}
              </p>
              <p className={styles.muted}>
                {e.operation === "SUPPRESS"
                  ? "Solicitud de no guardar"
                  : e.operation === "CONFLICT"
                    ? "Conflicto de identidad"
                    : "Interés registrado"}{" "}
                ·{" "}
                {new Date(e.created_at).toLocaleString("es-CO", {
                  timeZone: "America/Bogota",
                })}
              </p>
              {e.evidence.map((v, i) => (
                <blockquote key={`${v.message_id}-${i}`}>
                  <p>{v.quote}</p>
                  <small>
                    {e.transcription_sources?.some(
                      (source) => source.message_id === v.message_id,
                    )
                      ? "Fuente: transcripción automática de audio"
                      : "Fuente: texto escrito por el contacto"}
                  </small>
                </blockquote>
              ))}
              <Link href={prospectConversationLink(tenant, e.conversation_id)}>
                Abrir conversación de esta fuente
              </Link>
            </article>
          ))}
          {!detail.events.items.length ? (
            <p>Sin fuentes en esta página.</p>
          ) : null}
          {nextEvents ? <Link href={nextEvents}>Más fuentes</Link> : null}
        </div>
      </div>
    </section>
  );
}
