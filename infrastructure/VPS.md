# AI Workers — VPS

Deployment directory: `/opt/aiworkers` on the existing Zuvel VPS.
Public hostname: `aiworkers.zuvel.ai` (DNS and certificate must be ready first).
The existing website on port 3100 and OpenClaw are separate services.

## Build and run

Keep `.env` private (mode 600); never commit it or add it to a Docker image.
Preserve `APP_MASTER_KEY`, which decrypts existing tenant credentials.

```sh
docker compose -f compose.vps.yml config --quiet
docker compose -f compose.vps.yml build backend control-plane
docker compose -f compose.vps.yml up -d backend control-plane
curl --fail http://127.0.0.1:8100/health/ready
curl --fail http://127.0.0.1:3200/health/ready
```

Redis has no host port. Backend and dashboard bind to loopback only.
Nginx forwards HTTPS to port 3200 and the exact WhatsApp webhook route to
port 8100. Do not expose the backend directly.

## DNS and HTTPS

Create an A record `aiworkers` pointing to `187.77.18.99`.
Start with DNS-only and obtain a certificate using the existing Certbot
installation and the webroot `/var/www/aiworkers-acme`.
The HTTP server in `aiworkers.nginx.conf` can be enabled before issuance;
enable its HTTPS server only once the certificate exists.
Always run `nginx -t` before reload. Do not replace existing Zuvel sites.
If enabling Cloudflare proxy later, use Full (strict), not Flexible, and
do not cache authenticated dashboard pages or webhook requests.

## Worker cutover

The local installation and VPS share the same database, but have separate
Redis queues. Do not start the VPS scheduler while the local scheduler is
still dispatching outbox jobs. Drain and stop local workers first, check
pending jobs, then start the VPS workers. Do not flush Redis or delete
outbox records as a shortcut.

```sh
docker compose -f compose.vps.yml up -d agent-worker knowledge-worker outbound-worker scheduler
```

## Meta

App ID: `4513182438959780`.
Embedded Signup configuration ID: `1175786281496645`.
Its token configuration expires after 60 days; operational renewal is needed.
Check the actual app secret securely before attempting signup. Merely having
a value in the environment does not establish that it belongs to this app.
Configure the public domain in Meta and validate the complete signup flow
before considering the WhatsApp connection ready.

## Rollback and status

```sh
docker compose -f compose.vps.yml ps
docker compose -f compose.vps.yml stop
```

Stopping only this Compose project leaves the existing website and OpenClaw
running. Do not use `down -v`: Redis data must be retained.
For a later release, retain the previous image tags before rebuilding.
