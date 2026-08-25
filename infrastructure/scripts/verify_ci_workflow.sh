#!/usr/bin/env sh

set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

workflow=.github/workflows/ci.yml

fail() {
  printf '%s\n' "verify_ci_workflow: $*" >&2
  exit 1
}

require_line() {
  grep -Fqx -- "$2" "$1" || fail "missing required line in $1: $2"
}

test -f "$workflow" || fail "missing workflow: $workflow"

require_line "$workflow" '  pull_request:'
require_line "$workflow" '  push:'
require_line "$workflow" '      - main'
require_line "$workflow" 'permissions:'
require_line "$workflow" '  contents: read'
require_line "$workflow" 'concurrency:'
require_line "$workflow" '  group: ${{ github.workflow }}-${{ github.ref }}'
require_line "$workflow" '  cancel-in-progress: true'
require_line "$workflow" '  ci-baseline:'
require_line "$workflow" '    name: ci-baseline'
require_line "$workflow" '    runs-on: ubuntu-24.04'

for action in \
  'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1' \
  'actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0' \
  'actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0' \
  'astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1' \
  'pnpm/action-setup@0977fd99725f1db4007ccb2928dbb4e90d06cc86 # v6.0.10'
do
  grep -Fq -- "uses: $action" "$workflow" || fail "missing pinned action: $action"
done

require_line "$workflow" "          python-version: '3.12'"
require_line "$workflow" "          node-version: '24'"
require_line "$workflow" "          version: '0.12.5'"
require_line "$workflow" "          version: '11.24.0'"
require_line "$workflow" '      - run: uv sync --locked'
require_line "$workflow" '      - run: pnpm install --frozen-lockfile'

for command in \
  'make format-check' \
  'make lint' \
  'make typecheck' \
  'make test-unit' \
  'docker compose config --quiet' \
  'make test-security'
do
  require_line "$workflow" "      - run: $command"
done

if grep -Eq '^[[:space:]]*pull_request_target:' "$workflow"; then
  fail 'pull_request_target is forbidden'
fi

if grep -Eq 'secrets\.|[[:space:]](AWS|VERCEL|NETLIFY|CLOUDFLARE|DIGITALOCEAN|HOSTINGER)_[A-Z0-9_]*' "$workflow"; then
  fail 'provider or deployment credentials are forbidden'
fi

uses_count=$(grep -Ec '^[[:space:]]*-[[:space:]]+uses:' "$workflow" || true)
test "$uses_count" -eq 5 || fail "expected exactly five action uses, found: $uses_count"

printf '%s\n' 'verify_ci_workflow: CI workflow contract passed'
