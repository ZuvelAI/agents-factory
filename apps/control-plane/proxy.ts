import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { hasPlatformAdminRole } from "./lib/auth";
import { approvalResponse } from "./lib/approval-security";

export async function proxy(request: NextRequest): Promise<NextResponse> {
  if (
    request.nextUrl.pathname === "/approval" ||
    request.nextUrl.pathname.startsWith("/approval/")
  ) {
    return approvalResponse(request);
  }
  if (
    request.nextUrl.pathname === "/login" ||
    request.nextUrl.pathname === "/health/ready"
  ) {
    return NextResponse.next({ request });
  }

  let response = NextResponse.next({ request });
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !publishableKey) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const client = createServerClient(url, publishableKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (cookiesToSet) => {
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value);
        }
        response = NextResponse.next({ request });
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options);
        }
      },
    },
  });

  const { data, error } = await client.auth.getClaims();
  if (error || !hasPlatformAdminRole(data?.claims)) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/static(?:/|$)|_next/image(?:/|$)|favicon\\.ico$).*)"],
};
