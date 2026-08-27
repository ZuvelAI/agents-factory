#!/usr/bin/env sh

set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

fail() {
  printf '%s\n' "smoke_compose: $*" >&2
  exit 1
}

require_file() {
  test -f "$1" || fail "missing required file: $1"
}

require_line() {
  grep -Fqx -- "$2" "$1" || fail "missing required line in $1: $2"
}

for manifest in \
  pyproject.toml \
  uv.lock \
  package.json \
  pnpm-workspace.yaml \
  pnpm-lock.yaml \
  Makefile \
  .env.example \
  docker-compose.yml \
  apps/backend/pyproject.toml \
  apps/control-plane/package.json \
  workers/agent-worker/pyproject.toml \
  workers/knowledge-worker/pyproject.toml \
  workers/outbound-worker/pyproject.toml \
  workers/scheduler/pyproject.toml
do
  require_file "$manifest"
done

require_line pyproject.toml 'requires-python = ">=3.12,<3.14"'
require_line pyproject.toml 'required-version = "==0.12.5"'
require_line package.json '  "packageManager": "pnpm@11.24.0",'
require_line package.json '    "node": ">=22",'
require_line package.json '    "supabase": "2.115.0"'
require_line apps/backend/pyproject.toml '  "openai-agents==0.22.0",'
require_line apps/control-plane/package.json '    "dev": "next dev",'
require_line apps/control-plane/package.json '    "next": "16.3.2",'

require_line .env.example 'ENVIRONMENT='
require_line .env.example 'LOG_LEVEL='
require_line .env.example 'DATABASE_URL='
require_line .env.example 'REDIS_URL='
require_line .env.example 'SUPABASE_URL='
require_line .env.example 'SUPABASE_PUBLISHABLE_KEY='
require_line .env.example 'SUPABASE_JWT_ISSUER='
require_line .env.example 'SUPABASE_JWT_AUDIENCE='
require_line .env.example 'APP_MASTER_KEY='

if grep -Ev '^(#.*|[A-Z][A-Z0-9_]*=)$' .env.example | grep -q .; then
  fail '.env.example must contain only comments and empty environment values'
fi

for service in control-plane backend agent-worker knowledge-worker outbound-worker scheduler redis
do
  grep -Eq "^[[:space:]]{2}${service}:$" docker-compose.yml || \
    fail "missing Compose service: $service"
done

grep -Fq 'condition: service_healthy' docker-compose.yml || \
  fail 'Compose dependency ordering must wait for a healthy dependency'

healthcheck_count=$(grep -c '^[[:space:]]*healthcheck:' docker-compose.yml || true)
test "$healthcheck_count" -eq 7 || \
  fail "expected seven Compose healthchecks, found: $healthcheck_count"

grep -Fq '/health/ready' docker-compose.yml || \
  fail 'application healthchecks must fail closed against future readiness endpoints'

if grep -Eq '^[[:space:]]{2}supabase:$' docker-compose.yml; then
  fail 'Supabase must remain external to application Compose'
fi

for command in uv pnpm docker
do
  command -v "$command" >/dev/null 2>&1 || fail "required command is unavailable: $command"
done

uv sync --locked
pnpm install --frozen-lockfile
docker compose config --quiet

printf '%s\n' 'smoke_compose: locked workspace and Compose configuration checks passed'
