import type { TestRunInspector as Inspector } from "../../lib/conversations";

export function RunInspector({ run }: { run: Inspector }) {
  const sections = [
    ["AgentSpec", run.agent_spec],
    ["Knowledge", run.knowledge ?? { status: "Not bound" }],
    ["Identity", run.identity],
    ["Tools", run.tools],
    ["Sources", run.sources],
    ["Action", run.action],
    ["Approval", run.approval],
    ["Usage & cost", run.usage],
  ] as const;
  return (
    <section className="run-inspector" aria-live="polite">
      <header>
        <div>
          <p className="eyebrow">Run inspector</p>
          <h3>{run.simulated ? "Simulated result" : "Real test result"}</h3>
        </div>
        <span className="review-state review-test">{run.mode}</span>
      </header>
      <blockquote>{run.response}</blockquote>
      <dl className="run-summary">
        <div>
          <dt>Intent</dt>
          <dd>{run.intent}</dd>
        </div>
        <div>
          <dt>Capability</dt>
          <dd>{run.capability}</dd>
        </div>
        <div>
          <dt>Latency</dt>
          <dd>{run.latency_ms} ms</dd>
        </div>
        <div>
          <dt>Trace</dt>
          <dd>{run.trace_id}</dd>
        </div>
      </dl>
      <div className="inspector-grid">
        {sections.map(([title, value]) => (
          <article key={title}>
            <h4>{title}</h4>
            <pre>{JSON.stringify(value, null, 2)}</pre>
          </article>
        ))}
      </div>
    </section>
  );
}
