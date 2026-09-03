import type { TestMode, TestReadiness } from "../../lib/conversations";

export function ModeSelector({
  mode,
  onChange,
  readiness,
}: {
  mode: TestMode;
  onChange: (mode: TestMode) => void;
  readiness: TestReadiness;
}) {
  return (
    <fieldset className="mode-selector">
      <legend>Execution mode</legend>
      <label>
        <input
          checked={mode === "SANDBOX_SIMULATED"}
          name="testMode"
          onChange={() => onChange("SANDBOX_SIMULATED")}
          type="radio"
        />
        <span>
          <strong>Sandbox simulated</strong>
          <small>Fake tools only. Production writes are impossible.</small>
        </span>
      </label>
      <label
        className={!readiness.real_test_available ? "mode-unavailable" : ""}
      >
        <input
          checked={mode === "REAL_TEST_ENVIRONMENT"}
          disabled={!readiness.real_test_available}
          name="testMode"
          onChange={() => onChange("REAL_TEST_ENVIRONMENT")}
          type="radio"
        />
        <span>
          <strong>Real test environment</strong>
          <small>
            {readiness.real_test_available
              ? "Uses only dedicated test tenant accounts."
              : readiness.real_test_reason}
          </small>
        </span>
      </label>
    </fieldset>
  );
}
