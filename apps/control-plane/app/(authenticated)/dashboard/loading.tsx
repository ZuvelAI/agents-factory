export default function DashboardLoading() {
  return (
    <div className="dashboard-page" aria-busy="true" aria-live="polite">
      <header className="page-heading">
        <p className="eyebrow">Operations overview</p>
        <h1>Operational dashboard</h1>
        <p>Loading the latest measured status…</p>
      </header>
      <div className="metric-grid" aria-hidden="true">
        {[0, 1, 2, 3].map((item) => (
          <div className="metric-card metric-card-loading" key={item} />
        ))}
      </div>
    </div>
  );
}
