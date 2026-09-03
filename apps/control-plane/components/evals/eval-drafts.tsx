import Link from "next/link";

import type { EvalCaseDraft } from "../../lib/conversations";
import type { QualityGateOverview } from "../../lib/operations";

export function EvalDrafts({
  tenantId,
  drafts,
  qualityGate,
}: {
  tenantId: string;
  drafts: EvalCaseDraft[];
  qualityGate: QualityGateOverview;
}) {
  return (
    <div className="evals-workspace">
      <section className="eval-draft-list">
        <header>
          <p className="eyebrow">Review-only candidates</p>
          <h2>Eval Runner v0 Drafts</h2>
          <p>
            Sanitized Drafts become release evidence only after review and
            registration in a versioned tenant suite.
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
      <section className="operational-card">
        <span
          className={`review-state review-${qualityGate.latest?.passed ? "healthy" : "unavailable"}`}
        >
          {qualityGate.latest?.passed ? "Passed" : "Blocked"}
        </span>
        <h2>Production Quality Gate</h2>
        {qualityGate.latest ? (
          <>
            <p>
              {qualityGate.latest.passed_cases} passed ·{" "}
              {qualityGate.latest.failed_cases} failed. Evidence is valid only
              for the displayed exact digests.
            </p>
            <code>{qualityGate.latest.id}</code>
          </>
        ) : (
          <p>No Quality Gate run has been recorded for this tenant.</p>
        )}
      </section>
    </div>
  );
}
