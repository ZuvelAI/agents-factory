import { NextResponse, type NextRequest } from "next/server";
import { approvalOrigin } from "./approval-origin";

export function approvalResponse(request: NextRequest): NextResponse {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const origin = approvalOrigin();
  const csp = [
    "default-src 'none'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    `style-src 'self' 'nonce-${nonce}'`,
    "connect-src 'self'",
    "img-src 'self'",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(origin?.protocol === "https:" ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);
  let response: NextResponse;
  if (!origin || request.headers.get("host") !== origin.host) {
    response = new NextResponse("Revisión no disponible.", { status: 503 });
  } else if (
    request.nextUrl.pathname !== "/approval/review" ||
    request.nextUrl.search
  ) {
    // Never reflect a bearer supplied as a path/query into a redirect/error page.
    response = new NextResponse("Enlace no disponible.", { status: 404 });
  } else if (
    request.method === "POST" &&
    request.headers.get("origin") !== origin.origin
  ) {
    response = new NextResponse("Solicitud no permitida.", { status: 403 });
  } else if (!["GET", "HEAD", "POST"].includes(request.method)) {
    response = new NextResponse(null, { status: 405 });
  } else {
    response = NextResponse.next({ request: { headers } });
  }
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set(
    "Cache-Control",
    "private, no-store, max-age=0, must-revalidate",
  );
  response.headers.set("Referrer-Policy", "no-referrer");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=()",
  );
  return response;
}
