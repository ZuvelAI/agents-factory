import { reviewKnowledgeProposal } from "../../app/actions";
import type { KnowledgeProposal, KnowledgeSource } from "../../lib/knowledge";
import { AuthorityBadge } from "./authority-badge";

export function ProposalReview({
  proposal,
  source,
  tenantId,
}: {
  proposal: KnowledgeProposal;
  source?: KnowledgeSource;
  tenantId: string;
}) {
  const payload = proposal.proposed_payload;
  const authority = String(
    payload.authority ?? "REFERENCE",
  ) as KnowledgeSource["authority"];
  const isOpen = proposal.state === "PROPOSED";
  return (
    <article className="knowledge-card proposal-card">
      <header>
        <div>
          <p className="eyebrow">
            {proposal.proposed_by === "AI" ? "AI proposal" : "Source proposal"}
          </p>
          <h3>{proposalTitle(proposal)}</h3>
        </div>
        <span className={`review-state review-${proposal.state.toLowerCase()}`}>
          {proposal.state}
        </span>
      </header>
      <div className="proposal-provenance">
        <AuthorityBadge authority={authority} />
        <span>Source: {source?.name ?? proposal.source_id}</span>
        <span>Digest: {shortDigest(proposal.content_digest)}</span>
      </div>
      <p className="proposal-preview">{proposalPreview(proposal)}</p>
      {isOpen ? (
        <div className="proposal-actions">
          <DecisionForm
            decision="APPROVE"
            proposal={proposal}
            tenantId={tenantId}
          />
          <DecisionForm
            decision="REJECT"
            proposal={proposal}
            tenantId={tenantId}
          />
          <form action={reviewKnowledgeProposal} className="proposal-edit-form">
            <CommonFields proposal={proposal} tenantId={tenantId} />
            <input name="decision" type="hidden" value="EDIT" />
            <input
              name="sourceId"
              type="hidden"
              value={String(payload.source_id)}
            />
            <input name="authority" type="hidden" value={authority} />
            <input
              name="locator"
              type="hidden"
              value={JSON.stringify(payload.locator ?? {})}
            />
            <input
              name="contentDigest"
              type="hidden"
              value={String(payload.content_digest ?? proposal.content_digest)}
            />
            {proposal.artifact_type === "FACT" ? (
              <>
                <input
                  name="factKey"
                  type="hidden"
                  value={String(payload.key)}
                />
                <input
                  name="factKind"
                  type="hidden"
                  value={String(payload.kind)}
                />
                <label>
                  Approved structured value
                  <textarea
                    aria-label={`Approved value ${proposal.id}`}
                    defaultValue={JSON.stringify(payload.value ?? {}, null, 2)}
                    name="factValue"
                    required
                    rows={4}
                  />
                </label>
              </>
            ) : (
              <>
                <input
                  name="documentCategory"
                  type="hidden"
                  value={String(payload.category)}
                />
                <label>
                  Approved title
                  <input
                    defaultValue={String(payload.title)}
                    name="documentTitle"
                    required
                  />
                </label>
                <label>
                  Approved content
                  <textarea
                    defaultValue={String(payload.text)}
                    name="documentText"
                    required
                    rows={5}
                  />
                </label>
              </>
            )}
            <button className="secondary-button" type="submit">
              Save edited value
            </button>
          </form>
        </div>
      ) : null}
    </article>
  );
}

function CommonFields({
  proposal,
  tenantId,
}: {
  proposal: KnowledgeProposal;
  tenantId: string;
}) {
  return (
    <>
      <input name="tenantId" type="hidden" value={tenantId} />
      <input name="proposalId" type="hidden" value={proposal.id} />
      <input name="revision" type="hidden" value={proposal.revision} />
      <input name="artifactType" type="hidden" value={proposal.artifact_type} />
    </>
  );
}

function DecisionForm({
  decision,
  proposal,
  tenantId,
}: {
  decision: "APPROVE" | "REJECT";
  proposal: KnowledgeProposal;
  tenantId: string;
}) {
  return (
    <form action={reviewKnowledgeProposal}>
      <CommonFields proposal={proposal} tenantId={tenantId} />
      <input name="decision" type="hidden" value={decision} />
      <button
        className={decision === "REJECT" ? "quiet-danger-button" : ""}
        type="submit"
      >
        {decision === "APPROVE" ? "Approve proposal" : "Reject proposal"}
      </button>
    </form>
  );
}

function proposalTitle(proposal: KnowledgeProposal): string {
  const payload = proposal.proposed_payload;
  return proposal.artifact_type === "FACT"
    ? String(payload.key ?? "Structured fact")
    : String(payload.title ?? "Knowledge document");
}

function proposalPreview(proposal: KnowledgeProposal): string {
  const payload = proposal.proposed_payload;
  return proposal.artifact_type === "FACT"
    ? JSON.stringify(payload.value ?? {})
    : String(payload.text ?? "").slice(0, 280);
}

function shortDigest(digest: string): string {
  return `${digest.slice(0, 8)}…${digest.slice(-6)}`;
}
