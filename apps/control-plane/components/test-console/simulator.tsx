"use client";

import { useState, type FormEvent } from "react";

import { runTestConsole } from "../../app/actions";
import type {
  TestMode,
  TestReadiness,
  TestRunInspector,
} from "../../lib/conversations";
import { ModeSelector } from "./mode-selector";
import { RunInspector } from "./run-inspector";

export function Simulator({
  readiness,
  tenantId,
}: {
  readiness: TestReadiness;
  tenantId: string;
}) {
  const [mode, setMode] = useState<TestMode>("SANDBOX_SIMULATED");
  const [run, setRun] = useState<TestRunInspector | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const message = data.get("message");
    if (typeof message !== "string" || !message.trim()) return;
    setRunning(true);
    setError(null);
    const result = await runTestConsole({ tenantId, mode, message });
    if (result.ok) setRun(result.data);
    else setError(result.message);
    setRunning(false);
  }
  return (
    <div className="test-console-workspace">
      <form className="simulator-form form-section" onSubmit={submit}>
        <ModeSelector mode={mode} onChange={setMode} readiness={readiness} />
        <label>
          Customer message
          <textarea
            defaultValue="Please cancel order 1042."
            name="message"
            required
            rows={5}
          />
        </label>
        <p className="sandbox-guarantee">
          Sandbox records intent and simulated results; its external connector
          call count is always zero.
        </p>
        {error ? <p role="alert">{error}</p> : null}
        <button disabled={running} type="submit">
          {running ? "Running safe simulation…" : "Run test conversation"}
        </button>
      </form>
      {run ? (
        <RunInspector run={run} />
      ) : (
        <section className="state-panel">
          <span className="state-symbol">T</span>
          <h3>Ready to simulate</h3>
          <p>The exact run evidence will appear here.</p>
        </section>
      )}
    </div>
  );
}
