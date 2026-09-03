import Link from "next/link";

import type { EvalCaseDraft } from "../../lib/conversations";
import type { UnavailableFeature } from "../../lib/operations";

export function EvalDrafts({
  tenantId,
  drafts,
  qualityGate,
}: {
  tenantId: string;
  drafts: EvalCaseDraft[];
  qualityGate: UnavailableFeature;
}) {
  return (
    <div className="evals-workspace">
      <section className="eval-draft-list">
        <header>
          <p className="eyebrow">Review-only candidates</p>
          <h2>Eval Runner v0 Drafts</h2>
          <p>
            Sanitized Drafts are not release evidence until Task 45 registers
            them in the persistent learning loop.
          </p>
        </header>
        {drafts.map((draft) => (
          <article className="eval-summary-card" key={draft.id}>
            <span className="review-state review-draft">{draft.status}</span>
            <h3>{draft.case_id}</h3>
            <p>
              schema v{draft.schema_version} · source conversation{" "}
              <Link
                href={`/tenants/${tenantId}/conversations?conversation=${draft.conversation_id}`}
              >
                {draft.conversation_id}
              </Link>
            </p>
            <code>{draft.id}</code>
          </article>
        ))}
        {drafts.length === 0 ? (
          <p className="empty-state">No reviewed regression Drafts yet.</p>
        ) : null}
      </section>
      <section className="operational-card unavailable-card">
        <span className="review-state review-unavailable">Unavailable</span>
        <h2>Production Quality Gate</h2>
        <p>{qualityGate.reason}</p>
        <code>{qualityGate.code}</code>
        <button disabled type="button">
          Promote Drafts unavailable
        </button>
      </section>
    </div>
  );
}
