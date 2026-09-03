#!/usr/bin/env sh
set -eu

test "$#" -eq 4 || {
  printf '%s\n' 'usage: deploy.sh ENVIRONMENT RELEASE_TAG MIGRATION_VERSION SSH_KEY' >&2
  exit 64
}
environment=$1
release_tag=$2
migration_version=$3
ssh_key=$4

case "$environment" in STAGING|PRODUCTION) ;; *) exit 64 ;; esac
printf '%s' "$release_tag" | grep -Eq '^[A-Za-z0-9._-]{7,100}$'
printf '%s' "$migration_version" | grep -Eq '^[0-9]{14}$'
test -n "${DEPLOY_HOST:-}" && test -n "${DEPLOY_USER:-}"
test -f "$ssh_key" && test "$(stat -c '%a' "$ssh_key")" = 600

exec ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -i "$ssh_key" \
  "${DEPLOY_USER}@${DEPLOY_HOST}" -- \
  /opt/agents-factory/bin/promote-release "$environment" "$release_tag" "$migration_version"
