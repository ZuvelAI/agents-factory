#!/usr/bin/env sh
set -eu

drill_root=$(mktemp -d)
trap 'rm -rf "$drill_root"' EXIT HUP INT TERM
for asset in database storage configuration images external-mappings metadata; do
  mkdir -p "$drill_root/$asset"
  printf '%s\n' "fixture-$asset" >"$drill_root/$asset/sample"
done
infrastructure/scripts/backup_manifest.sh "$drill_root"
infrastructure/scripts/verify_restore.sh "$drill_root"
printf '%s\n' 'test_restore_drill: artifact rehearsal passed; full Staging drill remains external'
