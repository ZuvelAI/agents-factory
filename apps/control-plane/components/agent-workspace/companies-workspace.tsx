import Link from "next/link";
import { readCompanies } from "../../lib/agent-workspace";
import { CompanyCard } from "./company-card";

export type CompanySearch = { query?: string; cursor?: string };
export async function CompaniesWorkspace({
  search = {},
  title = "Tus empresas",
}: {
  search?: CompanySearch;
  title?: string;
}) {
  let data;
  try {
    data = await readCompanies(search.query, search.cursor);
  } catch {
    return (
      <section className="workspace">
        <p className="eyebrow">AI Workers</p>
        <h1>{title}</h1>
        <div className="workspace-empty" role="status">
          <h2>No pudimos cargar las empresas</h2>
          <p>
            Tu configuración no se ha modificado. Intenta consultar de nuevo.
          </p>
          <Link className="workspace-secondary" href="/tenants">
            Volver a consultar
          </Link>
        </div>
      </section>
    );
  }
  const count = data.items.reduce((n, c) => n + c.agent_count, 0);
  return (
    <section className="workspace">
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">Tu operación, en un vistazo</p>
          <h1>{title}</h1>
          <p className="workspace-muted">
            Todos tus agentes, en un solo lugar.
          </p>
        </div>
        <div>
          <button disabled title="Disponible en la siguiente entrega">
            + Nueva empresa
          </button>
          <small className="workspace-muted workspace-block">
            Creación disponible en la siguiente entrega
          </small>
        </div>
      </header>
      <form className="workspace-search" action="/tenants">
        <label htmlFor="company-search">Buscar empresa</label>
        <div>
          <input
            id="company-search"
            name="query"
            placeholder="Nombre de la empresa…"
            defaultValue={search.query}
            maxLength={200}
          />
          <button className="workspace-secondary" type="submit">
            Buscar
          </button>
        </div>
      </form>
      <div className="workspace-metrics">
        <div>
          <span>Empresas en esta página</span>
          <strong>{data.items.length}</strong>
        </div>
        <div>
          <span>Agentes de estas empresas</span>
          <strong>{count}</strong>
        </div>
        <div>
          <span>Estado de cada agente</span>
          <p>Consulta sus canales y versión</p>
        </div>
      </div>
      {data.items.length ? (
        <div className="workspace-grid">
          {data.items.map((company) => (
            <CompanyCard key={company.id} company={company} />
          ))}
        </div>
      ) : (
        <div className="workspace-empty">
          <h2>
            No hay empresas {search.query ? "con ese nombre" : "registradas"}
          </h2>
          <p>Esta vista muestra únicamente datos guardados.</p>
        </div>
      )}
      {data.next_cursor ? (
        <Link
          className="workspace-secondary"
          href={`/tenants?${new URLSearchParams({ ...(search.query ? { query: search.query } : {}), cursor: data.next_cursor })}`}
        >
          Más empresas →
        </Link>
      ) : null}
      <details className="workspace-advanced">
        <summary>Administración avanzada</summary>
        <p>El panel anterior sigue disponible durante la transición.</p>
        <Link href="/agents">Agentes y versiones</Link> ·{" "}
        <Link href="/operations">Operación técnica</Link>
      </details>
    </section>
  );
}
