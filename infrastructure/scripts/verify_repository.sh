#!/usr/bin/env sh

set -eu

fail() {
  printf '%s\n' "repository verification failed: $1" >&2
  exit 1
}

[ "$(git branch --show-current)" = "main" ] || fail "current branch is not main"
git remote get-url origin >/dev/null 2>&1 || fail "origin remote is missing"

visibility="$(/private/tmp/gh_2.98.0_macOS_arm64/bin/gh repo view --json visibility --jq .visibility)" \
  || fail "unable to read repository visibility"
[ "$visibility" = "PRIVATE" ] || fail "repository visibility is not PRIVATE"

[ -f docs/superpowers/specs/2026-08-12-agents-factory-master-product-architecture.md ] \
  || fail "canonical specification is missing"
[ -f 'Agents Factory Client Onboarding Playbook.pdf' ] || fail "client onboarding playbook is missing"

[ -z "$(git status --short)" ] || fail "worktree is not clean"

printf '%s\n' 'repository verification passed'
