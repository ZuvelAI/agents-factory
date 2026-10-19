import { expect, it } from "vitest";
import { parsePublicationRun } from "../../lib/workspace-publication";

const identity = "019c2000-0000-7000-8000-000000000601";
const run = {
  id: identity,
  version_id: identity,
  agent_instance_id: identity,
  draft_revision: 1,
  source_kind: "AGENT_CONFIGURATION",
  run_kind: "SCENARIOS",
  is_current: true,
  approved: null,
  expires_at: "2026-10-19T12:00:00Z",
  input_messages: null,
};
const proposal = {
  operation: "CAPTURE",
  simulated: true,
  declared_name: null,
  declared_company: null,
  service_interest: "Agente de ventas",
  need_summary: "Automatizar ventas",
  corrected_fields: [],
  evidence: [
    { message_id: identity, quote: "Quiero un agente para mi empresa" },
  ],
};
const keys = [
  "greeting",
  "known_fact",
  "unknown_fact",
  "scope",
  "injection",
  "lead_interest",
  "lead_no_interest",
  "lead_refusal",
  "human_control",
];
function suite() {
  return {
    ...run,
    result: {
      schema_version: 2,
      checks_passed: true,
      scenarios: keys.map((key) => ({
        key,
        prompt: "Prueba",
        response: key === "human_control" ? null : "Respuesta",
        passed: true,
        error_code: null,
        lead_proposals:
          key === "lead_interest"
            ? [structuredClone(proposal)]
            : key === "lead_refusal"
              ? [
                  {
                    ...structuredClone(proposal),
                    operation: "SUPPRESS",
                    declared_name: null,
                    declared_company: null,
                    service_interest: null,
                    need_summary: null,
                  },
                ]
              : [],
      })),
    },
  };
}

it("accepts nine complete version-two scenarios with validated simulated data", () => {
  const result = parsePublicationRun(suite()).result;
  expect(result && "scenarios" in result && result.scenarios.length).toBe(9);
});
it("rejects missing commercial cases and mismatched simulated operations", () => {
  const missing = suite();
  missing.result.scenarios.pop();
  expect(() => parsePublicationRun(missing)).toThrow();
  const wrong = suite();
  wrong.result.scenarios.find(
    (s) => s.key === "lead_interest",
  )!.lead_proposals = [];
  expect(() => parsePublicationRun(wrong)).toThrow();
});
it("rejects a fake real-capture marker and malformed evidence", () => {
  const unsafe = suite();
  unsafe.result.scenarios.find(
    (s) => s.key === "lead_interest",
  )!.lead_proposals[0].simulated = false;
  expect(() => parsePublicationRun(unsafe)).toThrow();
  const foreign = suite();
  foreign.result.scenarios.find(
    (s) => s.key === "lead_interest",
  )!.lead_proposals[0].evidence[0].message_id = "not-an-id";
  expect(() => parsePublicationRun(foreign)).toThrow();
});
