import type { PreviewMessage } from "./workspace-publication";

export type RequestIdentity = { signature: string; key: string };
export function requestIdentity(
  previous: RequestIdentity | null,
  signature: string,
): RequestIdentity {
  return previous?.signature === signature
    ? previous
    : { signature, key: crypto.randomUUID() };
}

/** Retain complete recent turns; never truncate a generated answer silently. */
export function previewInput(
  history: PreviewMessage[],
  text: string,
): PreviewMessage[] {
  const recent = history.slice(-18);
  while (
    recent.length &&
    recent.reduce((n, m) => n + m.text.length, text.length) > 20000
  )
    recent.splice(0, 2);
  return [...recent, { role: "user", text }];
}
