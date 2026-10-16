import { expect, it } from "vitest";
import {
  publicationPath,
  parsePublicationRun,
} from "../../lib/workspace-publication";

it("rejects invalid scope identifiers rather than interpolating arbitrary paths", () => {
  expect(() => publicationPath("../other", "agent")).toThrow();
});

const preview = {
  id: "019c2000-0000-7000-8000-000000000601",
  version_id: "019c2000-0000-7000-8000-000000000602",
  agent_instance_id: "019c2000-0000-7000-8000-000000000501",
  draft_revision: 1,
  source_kind: "AGENT_CONFIGURATION",
  run_kind: "PREVIEW",
  is_current: true,
  approved: null,
  expires_at: "2026-10-17T12:00:00Z",
  input_messages: [{ role: "user", text: "Hola" }],
  result: { response: "Hola de Zuvel", error_code: null },
};

it("accepts a complete isolated preview contract", () => {
  expect(parsePublicationRun(preview).result).toEqual(preview.result);
});

it("rejects a preview disguised as passing scenario evidence", () => {
  expect(() =>
    parsePublicationRun({
      ...preview,
      result: { checks_passed: true, scenarios: [] },
    }),
  ).toThrow();
});

it("rejects unsupported source and incomplete result contracts", () => {
  expect(() =>
    parsePublicationRun({ ...preview, source_kind: "LEGACY" }),
  ).toThrow();
  expect(() =>
    parsePublicationRun({
      ...preview,
      result: { response: null, error_code: null },
    }),
  ).toThrow();
  expect(() => parsePublicationRun({})).toThrow();
});
