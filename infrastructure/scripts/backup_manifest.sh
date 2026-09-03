#!/usr/bin/env sh
set -eu

backup_root=${1:?usage: backup_manifest.sh BACKUP_ROOT [OUTPUT]}
output=${2:-$backup_root/manifest.sha256}
case "$backup_root" in /|"$HOME"|"") exit 64 ;; esac
test -d "$backup_root"
for asset in database storage configuration images external-mappings metadata; do
  test -e "$backup_root/$asset" || {
    printf '%s\n' "backup_manifest: missing durable asset $asset" >&2
    exit 1
  }
done

temporary="$output.tmp"
: >"$temporary"
find "$backup_root" -type f ! -name 'manifest.sha256' ! -name 'manifest.sha256.tmp' | \
  LC_ALL=C sort | while IFS= read -r path; do
    relative=${path#"$backup_root"/}
    checksum=$(shasum -a 256 "$path" | awk '{print $1}')
    printf '%s  %s\n' "$checksum" "$relative"
  done >"$temporary"
test -s "$temporary"
mv "$temporary" "$output"
printf '%s\n' "backup_manifest: wrote checksummed durable inventory"
