import Link from "next/link";

export type StatusTone = "healthy" | "attention" | "unknown" | "empty";

const labels: Record<StatusTone, string> = {
  healthy: "Healthy",
  attention: "Needs attention",
  unknown: "Unknown",
  empty: "Not configured",
};

export function StatusBadge({
  state,
  href,
  label = labels[state],
}: {
  state: StatusTone;
  href?: string;
  label?: string;
}) {
  const className = `status-badge status-${state}`;
  return href ? (
    <Link className={className} href={href}>
      <span aria-hidden="true" className="status-dot" />
      {label}
    </Link>
  ) : (
    <span className={className}>
      <span aria-hidden="true" className="status-dot" />
      {label}
    </span>
  );
}
