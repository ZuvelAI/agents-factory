import type { CapabilityAction } from "../../lib/configuration";

export function IdentityMatrix({ actions }: { actions: CapabilityAction[] }) {
  const byLevel = [0, 1, 2, 3].map((level) => ({
    level,
    count: actions.filter((action) => action.required_identity_level === level)
      .length,
  }));
  return (
    <section
      className="identity-matrix"
      aria-labelledby="identity-matrix-title"
    >
      <h3 id="identity-matrix-title">Identity assurance</h3>
      <p>
        Recognition and verification do not grant authorization. Each action
        keeps its independent minimum.
      </p>
      <dl>
        {byLevel.map(({ level, count }) => (
          <div key={level}>
            <dt>Level {level}</dt>
            <dd>{count} enabled actions</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
