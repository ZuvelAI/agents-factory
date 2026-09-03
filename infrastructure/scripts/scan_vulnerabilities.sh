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

"$tool_dir/grype" dir:. --only-fixed --fail-on critical --output json >"$output_dir/dependencies.json"
"$tool_dir/grype" docker:agents-factory-backend:test --only-fixed --fail-on critical --output json >"$output_dir/backend.json"
"$tool_dir/grype" docker:agents-factory-control-plane:test --only-fixed --fail-on critical --output json >"$output_dir/control-plane.json"
printf '%s\n' 'scan_vulnerabilities: no fixable critical dependency or image findings'
