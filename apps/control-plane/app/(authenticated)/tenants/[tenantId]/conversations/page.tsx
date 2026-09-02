import Link from "next/link";

import {
  ReviewLabels,
  categoryLabels,
} from "../../../../../components/conversations/review-labels";
import { Timeline } from "../../../../../components/conversations/timeline";
import { TracePanel } from "../../../../../components/conversations/trace-panel";
import { callAuthenticatedBackend } from "../../../../../lib/api";
import type {
  ConversationDetail,
  ConversationWorkspace,
} from "../../../../../lib/conversations";

export default async function TenantConversationsPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{
    category?: string;
    conversation?: string;
    draft?: string;
    error?: string;
    saved?: string;
  }>;
}) {
  const { tenantId } = await params;
  const query = await searchParams;
  const filter = query.category
    ? `?category=${encodeURIComponent(query.category)}`
    : "";
  const workspace = await callAuthenticatedBackend<ConversationWorkspace>(
    `/admin/tenants/${encodeURIComponent(tenantId)}/conversations/review-workspace${filter}`,
  );
  const selectedId = query.conversation ?? workspace.conversations[0]?.id;
  const detail = selectedId
    ? await callAuthenticatedBackend<ConversationDetail>(
        `/admin/tenants/${encodeURIComponent(tenantId)}/conversations/${encodeURIComponent(selectedId)}/review-detail`,
      )
    : null;
  return (
    <section className="tenant-section conversation-page">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Review and learning</p>
        <h2>Conversations</h2>
        <p>
          Review traces, classify outcomes and export only minimized, anonymized
          Eval Runner v0 Drafts.
        </p>
      </header>
      {query.error ? (
        <p className="form-notice form-notice-error" role="alert">
          The review operation could not be completed.
        </p>
      ) : null}
      {query.saved ? (
        <p className="form-notice form-notice-success" role="status">
          {query.saved === "eval"
            ? "Anonymized Eval Runner v0 Draft created for review."
            : "Human review saved."}
        </p>
      ) : null}
      <nav
        className="conversation-filters"
        aria-label="Conversation categories"
      >
        <Link href={`/tenants/${tenantId}/conversations`}>All</Link>
        {workspace.categories.map((category) => (
          <Link
            href={`/tenants/${tenantId}/conversations?category=${category}`}
            key={category}
          >
            {categoryLabels[category]}
          </Link>
        ))}
      </nav>
      <div className="conversation-workspace">
        <aside className="conversation-list" aria-label="Conversation results">
          {workspace.conversations.map((conversation) => (
            <Link
              className={
                conversation.id === selectedId
                  ? "conversation-row conversation-row-current"
                  : "conversation-row"
              }
              href={`/tenants/${tenantId}/conversations?conversation=${conversation.id}${query.category ? `&category=${query.category}` : ""}`}
              key={conversation.id}
            >
              <strong>{conversation.customer_reference}</strong>
              <span>
                {conversation.message_count} messages ·{" "}
                {conversation.control_state}
              </span>
              <small>
                {conversation.review?.labels.join(" · ") ?? "Awaiting review"}
              </small>
            </Link>
          ))}
          {!workspace.conversations.length ? (
            <p>No conversations match this category.</p>
          ) : null}
        </aside>
        {detail ? (
          <div className="conversation-detail">
            <Timeline messages={detail.messages} />
            <TracePanel messages={detail.messages} />
            <ReviewLabels
              categories={workspace.categories}
              conversation={detail.conversation}
              labels={workspace.labels}
              tenantId={tenantId}
            />
          </div>
        ) : (
          <div className="state-panel">
            <span className="state-symbol">0</span>
            <h3>No conversation selected</h3>
          </div>
        )}
      </div>
      {workspace.eval_drafts.length ? (
        <section className="eval-draft-list">
          <p className="eyebrow">Draft regressions</p>
          <h3>Awaiting Eval review</h3>
          {workspace.eval_drafts.map((draft) => (
            <details key={draft.id} open={draft.id === query.draft}>
              <summary>
                {draft.case_id} · schema v{draft.schema_version}
              </summary>
              <pre>{JSON.stringify(draft.payload, null, 2)}</pre>
            </details>
          ))}
        </section>
      ) : null}
    </section>
  );
}
