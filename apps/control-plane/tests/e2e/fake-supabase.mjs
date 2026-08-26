import { createServer } from "node:http";
import { generateKeyPairSync, sign } from "node:crypto";

const port = Number(process.env.FAKE_SUPABASE_PORT ?? "54321");
const issuer = `http://127.0.0.1:${port}/auth/v1`;
const { privateKey, publicKey } = generateKeyPairSync("rsa", {
  modulusLength: 2048,
});
const publicJwk = publicKey.export({ format: "jwk" });
const kid = "local-e2e-key";

function encode(value) {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

function issueToken(platformRole) {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    iss: issuer,
    aud: "authenticated",
    exp: now + 300,
    iat: now,
    sub: platformRole
      ? "00000000-0000-4000-8000-000000000001"
      : "00000000-0000-4000-8000-000000000002",
    session_id: platformRole
      ? "00000000-0000-4000-8000-000000000011"
      : "00000000-0000-4000-8000-000000000012",
    role: "authenticated",
    is_anonymous: false,
    app_metadata: platformRole ? { platform_role: platformRole } : {},
    user_metadata: {},
  };
  const unsigned = `${encode({ alg: "RS256", kid, typ: "JWT" })}.${encode(payload)}`;
  const signature = sign(
    "RSA-SHA256",
    Buffer.from(unsigned),
    privateKey,
  ).toString("base64url");
  return `${unsigned}.${signature}`;
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function json(response, status, body) {
  response.writeHead(status, {
    "content-type": "application/json",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(body));
}

createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", issuer);
  if (
    request.method === "GET" &&
    url.pathname === "/auth/v1/.well-known/jwks.json"
  ) {
    json(response, 200, {
      keys: [{ ...publicJwk, alg: "RS256", kid, use: "sig" }],
    });
    return;
  }

  if (
    request.method === "POST" &&
    url.pathname === "/auth/v1/token" &&
    url.searchParams.get("grant_type") === "password"
  ) {
    const body = await readJson(request);
    const platformRole =
      body.email === "admin@example.test" && body.password === "valid-admin"
        ? "platform_admin"
        : body.email === "user@example.test" && body.password === "valid-user"
          ? null
          : undefined;
    if (platformRole === undefined) {
      json(response, 400, {
        error: "invalid_grant",
        error_description: "provider detail must stay private",
      });
      return;
    }
    const accessToken = issueToken(platformRole);
    json(response, 200, {
      access_token: accessToken,
      refresh_token: `refresh-${platformRole ?? "user"}`,
      token_type: "bearer",
      expires_in: 300,
      expires_at: Math.floor(Date.now() / 1000) + 300,
      user: {
        id: platformRole
          ? "00000000-0000-4000-8000-000000000001"
          : "00000000-0000-4000-8000-000000000002",
        aud: "authenticated",
        role: "authenticated",
        app_metadata: platformRole ? { platform_role: platformRole } : {},
        user_metadata: {},
      },
    });
    return;
  }

  if (request.method === "POST" && url.pathname === "/auth/v1/logout") {
    response.writeHead(204);
    response.end();
    return;
  }

  json(response, 404, { error: "not_found" });
}).listen(port, "127.0.0.1");
