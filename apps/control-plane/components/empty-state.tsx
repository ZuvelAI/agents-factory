import Link from "next/link";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: { label: string; href: string };
}) {
  return (
    <section className="state-panel" aria-labelledby="empty-state-title">
      <span aria-hidden="true" className="state-symbol">
        +
      </span>
      <h2 id="empty-state-title">{title}</h2>
      <p>{description}</p>
      {action ? (
        <Link className="button-link" href={action.href}>
          {action.label}
        </Link>
      ) : null}
    </section>
  );
}
