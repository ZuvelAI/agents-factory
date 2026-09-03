export function TenantSectionPlaceholder({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <section className="tenant-section">
      <header className="page-heading compact-heading">
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p>{description}</p>
      </header>
      <div className="coming-step" role="status">
        This step will unlock when its approved milestone is implemented. Your
        tenant and Agent Draft remain saved.
      </div>
    </section>
  );
}
