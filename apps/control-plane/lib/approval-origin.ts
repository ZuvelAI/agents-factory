// Server configuration only. No host/origin inferred from user-controlled headers.
export function approvalOrigin(): URL | null {
  try {
    const url = new URL(process.env.APPROVAL_PUBLIC_ORIGIN ?? "");
    const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
    if (
      (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      url.pathname !== "/"
    )
      return null;
    return url;
  } catch {
    return null;
  }
}
