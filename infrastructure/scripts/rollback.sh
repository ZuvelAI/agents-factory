#!/usr/bin/env sh
set -eu

test "$#" -eq 3 || {
  printf '%s\n' 'usage: rollback.sh ENVIRONMENT PREVIOUS_RELEASE_TAG SSH_KEY' >&2
  exit 64
}
environment=$1
release_tag=$2
ssh_key=$3
case "$environment" in STAGING|PRODUCTION) ;; *) exit 64 ;; esac
printf '%s' "$release_tag" | grep -Eq '^[A-Za-z0-9._-]{7,100}$'
test -n "${DEPLOY_HOST:-}" && test -n "${DEPLOY_USER:-}"
test -f "$ssh_key"
exec ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -i "$ssh_key" \
  "${DEPLOY_USER}@${DEPLOY_HOST}" -- \
  /opt/agents-factory/bin/rollback-release "$environment" "$release_tag"
