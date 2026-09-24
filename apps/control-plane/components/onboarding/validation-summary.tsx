export function ValidationSummary({
  blockers,
  warnings,
}: {
  blockers: string[];
  warnings: string[];
}) {
  if (blockers.length === 0 && warnings.length === 0) {
    return (
      <div className="validation-summary validation-ok" role="status">
        Este paso no tiene bloqueos actuales.
      </div>
    );
  }

  return (
    <div className="validation-stack">
      {blockers.length > 0 ? (
        <details className="validation-summary validation-blocked">
          <summary>
            <strong>
              {blockers.length} pendientes para completar este paso
            </strong>
            <span>Ver detalles</span>
          </summary>
          <ul>
            {blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </details>
      ) : null}
      {warnings.length > 0 ? (
        <div className="validation-summary validation-warning">
          <strong>Ten en cuenta</strong>
          <ul>
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
