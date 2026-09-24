export function TestAction({ actions }: { actions: string[] }) {
  if (actions.length === 0) return null;
  return (
    <section className="test-actions" aria-labelledby="test-actions-title">
      <h2 id="test-actions-title">Pruebas requeridas</h2>
      <ul>
        {actions.map((action) => (
          <li key={action}>{action}</li>
        ))}
      </ul>
    </section>
  );
}
