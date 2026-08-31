import type { ReviewResult } from "../../lib/approval-contract";

export function ApprovalResult({ result }: { result?: ReviewResult }) {
  return (
    <section role="status" className="approval-result">
      <h2>{result ? "Decisión registrada" : "Enlace no disponible"}</h2>
      <p>
        {result
          ? result.customer_safe_explanation
          : "El enlace no es válido, venció o la solicitud ya fue cerrada. No se puede registrar otra decisión desde esta página."}
      </p>
      {result ? (
        <p>
          La solicitud quedó cerrada para los demás revisores. Puedes cerrar
          esta página.
        </p>
      ) : (
        <p>Si necesitas ayuda, contacta al responsable del negocio.</p>
      )}
    </section>
  );
}
