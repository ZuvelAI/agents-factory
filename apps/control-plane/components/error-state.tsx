export function ErrorState({
  title = "Dashboard unavailable",
  description = "We could not load the operational summary. The rest of the Control Plane remains available.",
  correlationId,
}: {
  title?: string;
  description?: string;
  correlationId?: string;
}) {
  return (
    <section className="state-panel state-panel-error" role="alert">
      <span aria-hidden="true" className="state-symbol">
        !
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
      {correlationId ? (
        <p className="support-detail">
          Support reference: <code>{correlationId}</code>
        </p>
      ) : null}
    </section>
  );
}
