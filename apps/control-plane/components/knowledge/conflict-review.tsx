import type { KnowledgeConflict } from "../../lib/knowledge";
import { AuthorityBadge } from "./authority-badge";

export function ConflictReview({ conflict }: { conflict: KnowledgeConflict }) {
  return (
    <article
      className={`knowledge-card conflict-card conflict-${conflict.state.toLowerCase()}`}
    >
      <header>
        <div>
          <p className="eyebrow">
            {conflict.critical ? "Critical conflict" : "Conflict"}
          </p>
          <h3>{conflict.fact_key ?? "Source conflict"}</h3>
        </div>
        <span className={`review-state review-${conflict.state.toLowerCase()}`}>
          {conflict.state}
        </span>
      </header>
      <div className="authority-comparison">
        <span>
          Existing <AuthorityBadge authority={conflict.existing_authority} />
        </span>
        <span>
          Proposed <AuthorityBadge authority={conflict.proposed_authority} />
        </span>
      </div>
      <p>
        {conflict.state === "OPEN"
          ? "Resolve the linked proposal before this Draft can enter Test."
          : `Resolved by human review: ${conflict.resolution}.`}
      </p>
    </article>
  );
}
