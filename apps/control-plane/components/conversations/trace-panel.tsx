import type { TimelineMessage } from "../../lib/conversations";

export function TracePanel({ messages }: { messages: TimelineMessage[] }) {
  const traced = messages.filter(
    (message) => Object.keys(message.runtime_metadata).length > 0,
  );
  return (
    <section className="trace-panel">
      <p className="eyebrow">Attributable trace</p>
      <h3>Agent and tool evidence</h3>
      {traced.map((message) => (
        <article key={message.id}>
          <strong>AgentSpec {message.agent_spec_version ?? "unknown"}</strong>
          <code>
            {String(
              message.runtime_metadata.agent_spec_digest ??
                "digest unavailable",
            )}
          </code>
          <pre>{JSON.stringify(message.runtime_metadata, null, 2)}</pre>
        </article>
      ))}
      {!traced.length ? (
        <p>No AI runtime trace is attached to this conversation.</p>
      ) : null}
    </section>
  );
}
