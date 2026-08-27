import "server-only";

import { createServerSupabaseClient, getVerifiedPlatformAdmin } from "./auth";

type BackendRequestOptions = RequestInit & { accessToken: string };

type SafeProblemDetails = {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  correlation_id: string;
};

export class BackendProblem extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId?: string;

  constructor(options: {
    status: number;
    code: string;
    message: string;
    correlationId?: string;
  }) {
    super(options.message);
    this.name = "BackendProblem";
    this.status = options.status;
    this.code = options.code;
    this.correlationId = options.correlationId;
  }
}

function isSafeProblemDetails(value: unknown): value is SafeProblemDetails {
  if (value === null || typeof value !== "object") return false;
  const problem = value as Record<string, unknown>;
  return (
    typeof problem.type === "string" &&
    typeof problem.title === "string" &&
    typeof problem.status === "number" &&
    typeof problem.detail === "string" &&
    typeof problem.code === "string" &&
    typeof problem.correlation_id === "string"
  );
}

export async function callBackend<T = unknown>(
  baseUrl: string,
  path: string,
  options: BackendRequestOptions,
): Promise<T> {
  const { accessToken, headers, ...requestOptions } = options;
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\")) {
    throw new BackendProblem({
      status: 500,
      code: "backend_path_invalid",
      message: "The backend request path is invalid.",
    });
  }
  let configuredUrl: URL;
  let url: URL;
  try {
    configuredUrl = new URL(baseUrl);
    url = new URL(path, `${baseUrl.replace(/\/$/, "")}/`);
  } catch {
    throw new BackendProblem({
      status: 500,
      code: "backend_path_invalid",
      message: "The backend request path is invalid.",
    });
  }
  if (url.origin !== configuredUrl.origin) {
    throw new BackendProblem({
      status: 500,
      code: "backend_path_invalid",
      message: "The backend request path is invalid.",
    });
  }
  const response = await fetch(url.toString(), {
    ...requestOptions,
    cache: options.cache ?? "no-store",
    headers: {
      Accept: "application/json, application/problem+json",
      ...headers,
      Authorization: `Bearer ${accessToken}`,
    },
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/problem+json")) {
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        body = null;
      }
      if (isSafeProblemDetails(body)) {
        throw new BackendProblem({
          status: body.status,
          code: body.code,
          message: body.detail,
          correlationId: body.correlation_id,
        });
      }
    }
    throw new BackendProblem({
      status: response.status,
      code: "backend_request_failed",
      message: "The backend request could not be completed.",
    });
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function callAuthenticatedBackend<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const client = await createServerSupabaseClient();
  const claims = await getVerifiedPlatformAdmin(client);
  if (!claims) {
    throw new BackendProblem({
      status: 401,
      code: "authentication_required",
      message: "A valid access token is required.",
    });
  }

  const { data, error } = await client.auth.getSession();
  if (error || !data.session?.access_token) {
    throw new BackendProblem({
      status: 401,
      code: "authentication_required",
      message: "A valid access token is required.",
    });
  }

  const baseUrl = process.env.BACKEND_API_URL;
  if (!baseUrl) {
    throw new BackendProblem({
      status: 503,
      code: "backend_configuration_missing",
      message: "The backend is not configured.",
    });
  }
  return callBackend<T>(baseUrl, path, {
    ...options,
    accessToken: data.session.access_token,
  });
}
