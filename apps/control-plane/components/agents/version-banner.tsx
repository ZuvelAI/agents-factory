export function VersionBanner({
  currentVersion,
  currentState,
  productionVersion,
}: {
  currentVersion: number;
  currentState: "DRAFT" | "TEST" | "QUALITY_GATE" | "PRODUCTION";
  productionVersion: number | null;
}) {
  const isDraft = currentState === "DRAFT";
  return (
    <aside className="version-banner" aria-label="Agent version status">
      <div>
        <span className="version-label">
          {isDraft ? "Draft in progress" : "Immutable release baseline"}
        </span>
        <strong>Version {currentVersion}</strong>
      </div>
      <p>
        {!isDraft
          ? `This version is ${currentState.replaceAll("_", " ").toLowerCase()}. Saving a change creates a separate Draft.`
          : productionVersion === null
            ? "Not published yet. Your saved setup remains editable as a Draft."
            : `Production stays on version ${productionVersion} until this Draft passes its release gates.`}
      </p>
    </aside>
  );
}
