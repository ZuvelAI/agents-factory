#!/usr/bin/env sh

set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

fail() {
  printf '%s\n' "check_repository_security: $*" >&2
  exit 1
}

if prohibited_env_files=$(git ls-files --cached --others --exclude-standard | \
  grep -E '(^|/)\.env($|\.)' | grep -Ev '(^|/)\.env\.example$'); then
  fail "tracked environment file is forbidden: $(printf '%s\n' "$prohibited_env_files" | sed -n '1p')"
fi

if git grep --untracked -nEi \
  -- '-----BEGIN( [A-Z0-9]+)? PRIVATE KEY-----' \
  ':!docs/**' ':!.env.example' >/dev/null; then
  fail 'private key material is forbidden'
fi

if git grep --untracked -nEi \
  -- '(^|[[:space:]])(API[_-]?KEY|ACCESS[_-]?KEY|CLIENT[_-]?SECRET|PRIVATE[_-]?KEY|PASSWORD|SECRET|TOKEN)[[:space:]]*[:=][[:space:]]*[^[:space:]#]+' \
  ':!docs/**' ':!.env.example' >/dev/null; then
  fail 'credential-like value is forbidden'
fi

for workflow in .github/workflows/*.yml .github/workflows/*.yaml
do
  test -f "$workflow" || continue

  if grep -Eq '^[[:space:]]*pull_request_target:' "$workflow"; then
    fail "pull_request_target is forbidden: $workflow"
  fi

  if ! grep -Fqx 'permissions:' "$workflow"; then
    fail "workflow must declare top-level read-only permissions: $workflow"
  fi

  if grep -Eq '^[[:space:]]*permissions:[[:space:]]*write-all|^[[:space:]]*[A-Za-z-]+:[[:space:]]*write([[:space:]#]|$)' "$workflow"; then
    fail "writable workflow permission is forbidden: $workflow"
  fi

  if grep -Eq '^[[:space:]]*-[[:space:]]+uses:' "$workflow" && \
    grep -E '^[[:space:]]*-[[:space:]]+uses:' "$workflow" | \
      grep -Ev '@[0-9a-f]{40}([[:space:]]*(#.*)?)$' >/dev/null; then
    fail "unpinned workflow action is forbidden: $workflow"
  fi

  if grep -Eqi 'secrets\.|^[[:space:]]*(environment|deployment):|\b(AWS|VERCEL|NETLIFY|CLOUDFLARE|DIGITALOCEAN|HOSTINGER)_[A-Z0-9_]+' "$workflow"; then
    fail "provider credentials or deployment behavior is forbidden: $workflow"
  fi

  if grep -E '(^|[[:space:]])(uv[[:space:]]+sync|pnpm[[:space:]]+install|npm[[:space:]]+install|pip[[:space:]]+install|uv[[:space:]]+pip[[:space:]]+install)' "$workflow" | \
    grep -Ev 'uv[[:space:]]+sync[[:space:]]+--locked|pnpm[[:space:]]+install[[:space:]]+--frozen-lockfile' >/dev/null; then
    fail "floating dependency installation is forbidden: $workflow"
  fi
done

if test -d apps/backend/tests/security && \
  find apps/backend/tests/security -type f -name '*.py' -print -quit | grep -q .; then
  uv run pytest apps/backend/tests/security
fi

if test -d supabase/tests && find supabase/tests -type f -print -quit | grep -q .; then
  pnpm supabase test db
fi

printf '%s\n' 'check_repository_security: repository and workflow security checks passed'
