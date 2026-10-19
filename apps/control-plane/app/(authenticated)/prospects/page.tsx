import Link from "next/link";
import {
  isWorkspaceId,
  readAgents,
  readCompanyOptions,
} from "../../../lib/agent-workspace";
import {
  readProspects,
  readProspect,
  readProspectEvents,
  type ProspectDetail as Detail,
} from "../../../lib/leads";
import { ProspectList } from "../../../components/leads/prospect-list";
import { ProspectDetail } from "../../../components/leads/prospect-detail";
import { ProspectFilters } from "../../../components/leads/prospect-filters";
import styles from "../../../components/leads/prospects.module.css";
type Query = {
  tenant?: string;
  agent?: string;
  q?: string;
  cursor?: string;
  prospect?: string;
  eventsCursor?: string;
  companiesCursor?: string;
  agentsCursor?: string;
};
export default async function Prospects({
  searchParams,
}: {
  searchParams?: Promise<Query>;
}) {
  const query = (await searchParams) ?? {};
  let companies: Awaited<ReturnType<typeof readCompanyOptions>>;
  let agents: Awaited<ReturnType<typeof readAgents>> | undefined;
  let prospects: Awaited<ReturnType<typeof readProspects>> | undefined;
  let tenant: string | undefined;
  try {
    for (const value of [query.tenant, query.agent, query.prospect])
      if (value && !isWorkspaceId(value)) throw new Error("Invalid scope");
    companies = await readCompanyOptions(query.companiesCursor);
    tenant = query.tenant ?? companies.items[0]?.id;
    if (tenant)
      [agents, prospects] = await Promise.all([
        readAgents(tenant, query.agentsCursor),
        readProspects(tenant, query),
      ]);
  } catch {
    return (
      <section className="workspace">
        <h1>Prospectos</h1>
        <div className="workspace-empty" role="alert">
          <h2>No pudimos consultar los prospectos</h2>
          <p>No se han modificado los datos. Intenta consultar de nuevo.</p>
          <Link href="/prospects">Volver a consultar</Link>
        </div>
      </section>
    );
  }
  if (!tenant || !agents || !prospects)
    return (
      <section className="workspace">
        <h1>Prospectos</h1>
        <p>No hay empresas disponibles.</p>
        <Link href="/tenants">Ver empresas</Link>
      </section>
    );
  function link(extra: Partial<Query>) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ ...query, tenant, ...extra }))
      if (v) p.set(k, v);
    return `/prospects?${p}`;
  }
  const selected = query.prospect ?? prospects.items[0]?.id;
  let detail: Detail | undefined,
    detailError = false;
  if (selected)
    try {
      detail = await readProspect(tenant, selected, query.agent);
      if (query.eventsCursor)
        detail.events = await readProspectEvents(
          tenant,
          selected,
          query.eventsCursor,
        );
    } catch {
      detailError = true;
    }
  const name =
    agents.company_name ??
    companies.items.find((c) => c.id === tenant)?.name ??
    "Empresa seleccionada";
  return (
    <section className="workspace">
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">
            Relaciones que empiezan con una conversación
          </p>
          <h1>Prospectos</h1>
          <p className="workspace-muted">
            {name} · Contactos con interés comercial, reunidos por empresa.
          </p>
        </div>
        <Link className="workspace-secondary" href={link({})}>
          Actualizar
        </Link>
      </header>
      <ProspectFilters>
        <div>
          <label htmlFor="prospect-company">Empresa</label>
          <select id="prospect-company" name="tenant" defaultValue={tenant}>
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
          <label htmlFor="prospect-agent">Agente</label>
          <select
            id="prospect-agent"
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
          <label htmlFor="prospect-search">Buscar prospectos</label>
          <input
            id="prospect-search"
            type="search"
            className={styles.search}
            name="q"
            defaultValue={query.q}
            maxLength={200}
            placeholder="Nombre, teléfono, usuario o empresa"
          />
        </div>
        <button type="submit" className="workspace-primary">
          Buscar
        </button>
      </ProspectFilters>
      <div className={styles.pagination}>
        {companies.next_cursor ? (
          <Link href={link({ companiesCursor: companies.next_cursor })}>
            Más empresas
          </Link>
        ) : null}
        {agents.next_cursor ? (
          <Link href={link({ agentsCursor: agents.next_cursor })}>
            Más agentes
          </Link>
        ) : null}
      </div>
      <div className={styles.layout}>
        <div>
          <ProspectList
            items={prospects.items}
            selected={selected}
            href={(id) => link({ prospect: id, eventsCursor: undefined })}
          />
          <div className={styles.pagination}>
            {query.cursor ? (
              <Link
                href={link({
                  cursor: undefined,
                  prospect: undefined,
                  eventsCursor: undefined,
                })}
              >
                Primera página
              </Link>
            ) : null}
            {prospects.next_cursor ? (
              <Link
                href={link({
                  cursor: prospects.next_cursor,
                  prospect: undefined,
                  eventsCursor: undefined,
                })}
              >
                Más prospectos
              </Link>
            ) : null}
          </div>
        </div>
        {detailError ? (
          <section className={styles.panel} role="alert">
            <div className={styles.empty}>
              <h2>No pudimos consultar este prospecto</h2>
              <p>
                Puede no pertenecer a la empresa o al agente seleccionado. No se
                ha cambiado ningún dato.
              </p>
            </div>
          </section>
        ) : detail ? (
          <ProspectDetail
            detail={detail}
            tenant={tenant}
            nextEvents={
              detail.events.next_cursor
                ? link({
                    prospect: selected,
                    eventsCursor: detail.events.next_cursor,
                  })
                : undefined
            }
          />
        ) : (
          <aside className={styles.empty}>
            Selecciona un prospecto para ver sus datos y las conversaciones de
            origen.
          </aside>
        )}
      </div>
    </section>
  );
}
