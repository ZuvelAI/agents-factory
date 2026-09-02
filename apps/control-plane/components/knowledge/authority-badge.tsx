import type { KnowledgeAuthority } from "../../lib/knowledge";

const labels: Record<KnowledgeAuthority, string> = {
  AUTHORITATIVE: "Authoritative",
  SECONDARY: "Secondary",
  REFERENCE: "Reference",
};

export function AuthorityBadge({
  authority,
}: {
  authority: KnowledgeAuthority;
}) {
  return (
    <span className={`authority-badge authority-${authority.toLowerCase()}`}>
      {labels[authority]}
    </span>
  );
}
