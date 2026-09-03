import type { KnowledgeDiff, KnowledgeSource } from "../../lib/knowledge";

export function VersionDiff({
  diff,
  source,
}: {
  diff: KnowledgeDiff;
  source?: KnowledgeSource;
}) {
  return (
    <article className="knowledge-card diff-card">
      <header>
        <div>
          <p className="eyebrow">Connected-source change</p>
          <h3>{source?.name ?? diff.source_id}</h3>
        </div>
        <span className={`review-state review-${diff.state.toLowerCase()}`}>
          {diff.state}
        </span>
      </header>
      <dl className="digest-diff">
        <div>
          <dt>Previous</dt>
          <dd>
            {diff.previous_digest
              ? shortDigest(diff.previous_digest)
              : "First version"}
          </dd>
        </div>
        <div>
          <dt>Current</dt>
          <dd>{shortDigest(diff.current_digest)}</dd>
        </div>
      </dl>
      <p>
        {String(
          diff.summary.message ??
            "A source change created a new Draft for review.",
        )}
      </p>
    </article>
  );
}

function shortDigest(digest: string): string {
  return `${digest.slice(0, 10)}…${digest.slice(-8)}`;
}
