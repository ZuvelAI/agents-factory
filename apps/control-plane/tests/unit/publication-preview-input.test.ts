import { expect, it } from "vitest";
import {
  previewInput,
  requestIdentity,
} from "../../lib/publication-preview-input";

it("keeps the request key through ambiguous retries and replaces it for changed input", () => {
  const first = requestIdentity(null, "same payload");
  expect(requestIdentity(first, "same payload")).toEqual(first);
  expect(requestIdentity(first, "different payload").key).not.toBe(first.key);
});
it("keeps whole recent turns within the total history budget, without truncating answers", () => {
  const turn = [
    { role: "user" as const, text: "x".repeat(2000) },
    { role: "assistant" as const, text: "a".repeat(8000) },
  ];
  const result = previewInput([...turn, ...turn, ...turn], "follow up");
  expect(result.map((m) => m.role)).toEqual(["user", "assistant", "user"]);
  expect(result[1].text).toHaveLength(8000);
  expect(result.reduce((n, m) => n + m.text.length, 0)).toBeLessThanOrEqual(
    20000,
  );
});
