import type { SimulatedLeadProposal } from "../../lib/lead-simulation";

export function LeadSimulationSummary({
  proposals,
}: {
  proposals?: SimulatedLeadProposal[];
}) {
  if (!proposals?.length) return null;
  return (
    <section className="workspace-card" aria-label="Captura simulada">
      <h3>Simulación · no se guardaron datos reales</h3>
      {proposals.map((proposal, index) => (
        <div key={index}>
          <p>
            {proposal.operation === "SUPPRESS"
              ? "Respetaría la negativa a registrar datos."
              : "Propondría guardar un prospecto."}
          </p>
          {proposal.service_interest && (
            <p>
              <strong>Interés:</strong> {proposal.service_interest}
            </p>
          )}
          {proposal.need_summary && (
            <p>
              <strong>Necesidad:</strong> {proposal.need_summary}
            </p>
          )}
          {proposal.declared_name && (
            <p>
              <strong>Nombre declarado:</strong> {proposal.declared_name}
            </p>
          )}
          {proposal.declared_company && (
            <p>
              <strong>Empresa declarada:</strong> {proposal.declared_company}
            </p>
          )}
          <details>
            <summary>Evidencia de esta prueba</summary>
            {proposal.evidence.map((e, n) => (
              <blockquote key={`${e.message_id}-${n}`}>{e.quote}</blockquote>
            ))}
          </details>
        </div>
      ))}
    </section>
  );
}
