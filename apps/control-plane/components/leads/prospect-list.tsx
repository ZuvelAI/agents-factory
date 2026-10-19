import Link from "next/link";
import { prospectName, type Prospect } from "../../lib/leads";
import styles from "./prospects.module.css";
export function ProspectList({
  items,
  selected,
  href,
}: {
  items: Prospect[];
  selected?: string;
  href: (id: string) => string;
}) {
  return (
    <section className={styles.panel} aria-label="Lista de prospectos">
      <div className={styles.panelHeading}>
        <h2>Contactos con interés</h2>
        <span className={styles.muted}>Más recientes primero</span>
      </div>
      {items.length ? (
        <ul className={styles.list}>
          {items.map((p) => (
            <li key={p.id}>
              <Link
                href={href(p.id)}
                className={`${styles.row} ${selected === p.id ? styles.selected : ""}`}
                aria-current={selected === p.id ? "true" : undefined}
              >
                <span className={styles.avatar} aria-hidden="true">
                  {prospectName(p).slice(0, 1).toUpperCase()}
                </span>
                <span className={styles.rowBody}>
                  <strong>{prospectName(p)}</strong>
                  <span className={styles.muted}>
                    {p.declared_company || "Empresa sin indicar"}
                  </span>
                  <span className={styles.interest}>
                    {p.service_interests.join(" · ") ||
                      "Interés sin especificar"}
                  </span>
                </span>
                <span className={styles.rowEnd}>
                  <span className={styles.badge}>Nuevo</span>
                  <time dateTime={p.updated_at}>
                    {new Date(p.updated_at).toLocaleDateString("es-CO", {
                      timeZone: "America/Bogota",
                    })}
                  </time>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <div className={styles.empty}>
          <h3>No hay prospectos para estos filtros</h3>
          <p>
            Solo aparecen contactos que hayan expresado interés comercial. Un
            saludo no crea un prospecto.
          </p>
        </div>
      )}
    </section>
  );
}
