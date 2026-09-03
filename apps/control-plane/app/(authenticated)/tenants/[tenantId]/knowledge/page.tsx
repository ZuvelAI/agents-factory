import type { ReactNode } from "react";

import {
  prepareKnowledgeEmbeddings,
  promoteKnowledgeToTest,
  syncKnowledgeSource,
} from "../../../../actions";
import { AuthorityBadge } from "../../../../../components/knowledge/authority-badge";
import { ConflictReview } from "../../../../../components/knowledge/conflict-review";
import { ProposalReview } from "../../../../../components/knowledge/proposal-review";
import { SourceForm } from "../../../../../components/knowledge/source-form";
import { VersionDiff } from "../../../../../components/knowledge/version-diff";
import { callAuthenticatedBackend } from "../../../../../lib/api";
import type {
  KnowledgeSource,
  KnowledgeVersionOverview,
  KnowledgeWorkspace,
} from "../../../../../lib/knowledge";

export default async function TenantKnowledgePage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ error?: string; saved?: string }>;
}) {
  const { tenantId } = await params;
  const query = await searchParams;
  const workspace = await callAuthenticatedBackend<KnowledgeWorkspace>(
    `/admin/tenants/${encodeURIComponent(tenantId)}/knowledge/workspace`,
  );
  const sources = new Map(
    workspace.sources.map(({ source }) => [source.id, source]),
  );
  const production = workspace.versions.find(
    ({ version }) => version.state === "PRODUCTION",
  );
  const newestDraft = workspace.versions.find(
    ({ version }) => version.state === "DRAFT",
  );

  return (
    <section className="tenant-section knowledge-page">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Guided setup</p>
        <h2>Knowledge review and versions</h2>
        <p>
          Configure each client source, inspect provenance, and approve exact
          content before it can move beyond Draft.
        </p>
      </header>
      <KnowledgeNotice error={query.error} saved={query.saved} />
      <div className="knowledge-release-banner">
        <div>
          <span className="version-label">Active Production</span>
          <strong>
            {production
              ? `v${production.version.version_number} · immutable`
              : "No version published"}
          </strong>
        </div>
        <p>
          {newestDraft
            ? `Draft v${newestDraft.version.version_number} — review required. The active Production version remains unchanged.`
            : "Connected-source changes will create a separate Draft review queue."}
        </p>
      </div>

      <SourceForm tenantId={tenantId} />

      <KnowledgeSection
        count={workspace.sources.length}
        eyebrow="Source registry"
        title="Configured sources"
      >
        <div className="knowledge-grid">
          {workspace.sources.map(({ source, latest_ingestion }) => (
            <article className="knowledge-card source-card" key={source.id}>
              <header>
                <div>
                  <p className="eyebrow">{sourceLabel(source.source_type)}</p>
                  <h3>{source.name}</h3>
                </div>
                <AuthorityBadge authority={source.authority} />
              </header>
              <p>
                Provenance is retained with every accepted fact or document.
              </p>
              <dl className="source-status">
                <div>
                  <dt>Latest sync</dt>
                  <dd>{latest_ingestion?.state ?? "Not synchronized"}</dd>
                </div>
                <div>
                  <dt>Proposals</dt>
                  <dd>{latest_ingestion?.proposed_artifact_count ?? 0}</dd>
                </div>
              </dl>
              <form action={syncKnowledgeSource}>
                <input name="tenantId" type="hidden" value={tenantId} />
                <input name="sourceId" type="hidden" value={source.id} />
                <button className="secondary-button" type="submit">
                  Synchronize source
                </button>
              </form>
            </article>
          ))}
        </div>
      </KnowledgeSection>

      <KnowledgeSection
        count={
          workspace.proposals.filter(({ state }) => state === "PROPOSED").length
        }
        eyebrow="Human review queue"
        title="Knowledge proposals"
      >
        <div className="knowledge-grid">
          {workspace.proposals.map((proposal) => (
            <ProposalReview
              key={proposal.id}
              proposal={proposal}
              source={sources.get(proposal.source_id)}
              tenantId={tenantId}
            />
          ))}
        </div>
      </KnowledgeSection>

      <KnowledgeSection
        count={
          workspace.conflicts.filter(({ state }) => state === "OPEN").length
        }
        eyebrow="Authority controls"
        title="Conflicts"
      >
        <div className="knowledge-grid">
          {workspace.conflicts.map((conflict) => (
            <ConflictReview conflict={conflict} key={conflict.id} />
          ))}
        </div>
      </KnowledgeSection>

      <KnowledgeSection
        count={workspace.diffs.length}
        eyebrow="Immutable change history"
        title="Source diffs"
      >
        <div className="knowledge-grid">
          {workspace.diffs.map((diff) => (
            <VersionDiff
              diff={diff}
              key={diff.id}
              source={sources.get(diff.source_id)}
            />
          ))}
        </div>
      </KnowledgeSection>

      <KnowledgeSection
        count={workspace.versions.length}
        eyebrow="Release workflow"
        title="Knowledge versions"
      >
        <div className="knowledge-version-list">
          {workspace.versions.map((overview) => (
            <VersionCard
              key={overview.version.id}
              overview={overview}
              tenantId={tenantId}
            />
          ))}
        </div>
        <div className="production-gate">
          <div>
            <strong>Production is fail-closed</strong>
            <p>{workspace.production_blocker}</p>
            <code>{workspace.production_blocker_code}</code>
          </div>
          <button disabled type="button">
            Publish Production
          </button>
        </div>
      </KnowledgeSection>
    </section>
  );
}

function KnowledgeSection({
  children,
  count,
  eyebrow,
  title,
}: {
  children: ReactNode;
  count: number;
  eyebrow: string;
  title: string;
}) {
  return (
    <section className="knowledge-section">
      <header className="knowledge-section-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h3>{title}</h3>
        </div>
        <span className="knowledge-count">{count}</span>
      </header>
      {children}
    </section>
  );
}

function VersionCard({
  overview,
  tenantId,
}: {
  overview: KnowledgeVersionOverview;
  tenantId: string;
}) {
  const { version } = overview;
  return (
    <article
      className={`knowledge-version version-${version.state.toLowerCase()}`}
    >
      <div>
        <p className="eyebrow">Version {version.version_number}</p>
        <h4>{version.name}</h4>
        <p>
          {overview.structured_fact_count} facts · {overview.document_count}{" "}
          documents · v0 {overview.v0_evaluation.toLowerCase()}
        </p>
        <small>
          Exact digest:{" "}
          {shortDigest(version.digest ?? overview.candidate_digest)}
        </small>
      </div>
      <span className={`review-state review-${version.state.toLowerCase()}`}>
        {version.state}
      </span>
      {version.state === "DRAFT" ? (
        <div className="version-actions">
          <form action={prepareKnowledgeEmbeddings}>
            <input name="tenantId" type="hidden" value={tenantId} />
            <input name="versionId" type="hidden" value={version.id} />
            <button className="secondary-button" type="submit">
              Prepare semantic index
            </button>
          </form>
          <form action={promoteKnowledgeToTest}>
            <input name="tenantId" type="hidden" value={tenantId} />
            <input name="versionId" type="hidden" value={version.id} />
            <button disabled={!overview.candidate_digest} type="submit">
              Promote to Test with v0 evals
            </button>
          </form>
        </div>
      ) : null}
    </article>
  );
}

function KnowledgeNotice({ error, saved }: { error?: string; saved?: string }) {
  if (error) {
    return (
      <p className="form-notice form-notice-error" role="alert">
        {error === "source-size"
          ? "The source file exceeds the 20 MB limit."
          : error === "source-file"
            ? "Choose a valid file for this source type."
            : "The Knowledge operation could not be completed. Review open proposals and conflicts."}
      </p>
    );
  }
  const messages: Record<string, string> = {
    source: "Source saved and synchronization requested.",
    sync: "Synchronization requested. Any change enters a new Draft review queue.",
    review: "Human review recorded with immutable provenance.",
    embeddings: "Semantic index preparation requested for this exact Draft.",
    test: "Knowledge version promoted to Test after the v0 readiness evaluation.",
  };
  return saved ? (
    <p className="form-notice form-notice-success" role="status">
      {messages[saved] ?? "Knowledge workspace updated."}
    </p>
  ) : null;
}

function sourceLabel(type: KnowledgeSource["source_type"]): string {
  return {
    WEBSITE: "Website",
    PDF: "PDF",
    DOCX: "Word document",
    GOOGLE_DRIVE: "Google Drive",
    SPREADSHEET: "Spreadsheet",
    MANUAL: "Manual entry",
  }[type];
}

function shortDigest(digest: string | null): string {
  return digest ? `${digest.slice(0, 10)}…${digest.slice(-8)}` : "Pending";
}
