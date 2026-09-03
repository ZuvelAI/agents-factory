#!/usr/bin/env sh
set -eu

output_dir=${1:-artifacts/vulnerability}
mkdir -p "$output_dir"
tool_dir=$(mktemp -d)
trap 'rm -rf "$tool_dir"' EXIT HUP INT TERM

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

version=0.116.1
asset="grype_${version}_linux_amd64.tar.gz"
base_url="https://github.com/anchore/grype/releases/download/v${version}"
curl -fsSL "$base_url/grype_${version}_checksums.txt" -o "$tool_dir/checksums.txt"
test "$(sha256_file "$tool_dir/checksums.txt")" = \
  38ffeb0fbdf1955e46ebfb3cb7369b78888168954a77df02985c0c06505f85e9
curl -fsSL "$base_url/$asset" -o "$tool_dir/$asset"
expected=$(awk -v asset="$asset" '$2 == asset {print $1}' "$tool_dir/checksums.txt")
test -n "$expected"
test "$(sha256_file "$tool_dir/$asset")" = "$expected"
tar -xzf "$tool_dir/$asset" -C "$tool_dir" grype

scan_source() {
  label=$1
  source=$2
  report=$3

  if "$tool_dir/grype" "$source" --only-fixed --fail-on critical --output json >"$report"; then
    return 0
  fi

  python3 - "$label" "$report" <<'PY'
import json
import sys

label, report = sys.argv[1:]
with open(report, encoding="utf-8") as handle:
    findings = json.load(handle).get("matches", [])

for finding in findings:
    vulnerability = finding.get("vulnerability", {})
    if vulnerability.get("severity") != "Critical":
        continue
    artifact = finding.get("artifact", {})
    fixed = ",".join(vulnerability.get("fix", {}).get("versions", [])) or "unknown"
    print(
        f"{label}: {vulnerability.get('id')} "
        f"{artifact.get('name')} {artifact.get('version')} -> {fixed}",
        file=sys.stderr,
    )
PY
  return 1
}

failed=0
scan_source dependencies dir:. "$output_dir/dependencies.json" || failed=1
scan_source backend docker:agents-factory-backend:test "$output_dir/backend.json" || failed=1
scan_source control-plane docker:agents-factory-control-plane:test "$output_dir/control-plane.json" || failed=1

if [ "$failed" -ne 0 ]; then
  printf '%s\n' 'scan_vulnerabilities: fixable critical findings detected' >&2
  exit 2
fi

printf '%s\n' 'scan_vulnerabilities: no fixable critical dependency or image findings'
