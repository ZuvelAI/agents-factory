#!/usr/bin/env sh

set -eu

fail() {
  printf '%s\n' "repository verification failed: $1" >&2
  exit 1
}

github_repository_from_origin() {
  case "$1" in
    https://github.com/*)
      repository="${1#https://github.com/}"
      ;;
    http://github.com/*)
      repository="${1#http://github.com/}"
      ;;
    git@github.com:*)
      repository="${1#git@github.com:}"
      ;;
    ssh://git@github.com/*)
      repository="${1#ssh://git@github.com/}"
      ;;
    *)
      return 1
      ;;
  esac

  repository="${repository%.git}"
  repository="${repository%/}"
  case "$repository" in
    */?*) printf '%s\n' "$repository" ;;
    *) return 1 ;;
  esac
}

[ "$(git branch --show-current)" = "main" ] || fail "current branch is not main"
origin_url="$(git remote get-url origin)" || fail "origin remote is missing"
github_repository="$(github_repository_from_origin "$origin_url")" \
  || fail "origin is not a GitHub repository URL"

gh_bin="${GH_BIN:-gh}"
command -v "$gh_bin" >/dev/null 2>&1 || fail "GitHub CLI '$gh_bin' is not available"

repository_details="$("$gh_bin" repo view "$github_repository" \
  --json nameWithOwner,visibility,defaultBranchRef \
  --jq '[.nameWithOwner, .visibility, .defaultBranchRef.name] | @tsv')" \
  || fail "unable to read origin repository details"
tab="$(printf '\t')"
IFS="$tab" read -r resolved_repository visibility default_branch <<EOF
$repository_details
EOF
[ "$resolved_repository" = "$github_repository" ] \
  || fail "GitHub repository does not match origin"
[ "$visibility" = "PRIVATE" ] || fail "repository visibility is not PRIVATE"
[ "$default_branch" = "main" ] || fail "repository default branch is not main"

local_head="$(git rev-parse HEAD)" || fail "unable to resolve local HEAD"
remote_ref="$(git ls-remote --exit-code origin refs/heads/main)" \
  || fail "unable to resolve origin/main"
remote_head="$(printf '%s\n' "$remote_ref" | awk 'NR == 1 {print $1}')"
[ -n "$remote_head" ] || fail "origin/main is missing"
[ "$remote_head" = "$local_head" ] || fail "origin/main does not match local HEAD"

[ -f docs/superpowers/specs/2026-08-12-agents-factory-master-product-architecture.md ] \
  || fail "canonical specification is missing"
[ -f 'Agents Factory Client Onboarding Playbook.pdf' ] || fail "client onboarding playbook is missing"

[ -z "$(git status --short)" ] || fail "worktree is not clean"

printf '%s\n' 'repository verification passed'
