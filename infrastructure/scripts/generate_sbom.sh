#!/usr/bin/env sh
set -eu

output_dir=${1:-artifacts/sbom}
mkdir -p "$output_dir"

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

tool_dir=$(mktemp -d)
trap 'rm -rf "$tool_dir"' EXIT HUP INT TERM
version=1.51.0
asset="syft_${version}_linux_amd64.tar.gz"
base_url="https://github.com/anchore/syft/releases/download/v${version}"
curl -fsSL "$base_url/syft_${version}_checksums.txt" -o "$tool_dir/checksums.txt"
test "$(sha256_file "$tool_dir/checksums.txt")" = \
  3d85f1d0e1266cae4346514124665f10b7cefd9cce815be13921d199917e5581
curl -fsSL "$base_url/$asset" -o "$tool_dir/$asset"
expected=$(awk -v asset="$asset" '$2 == asset {print $1}' "$tool_dir/checksums.txt")
test -n "$expected"
test "$(sha256_file "$tool_dir/$asset")" = "$expected"
tar -xzf "$tool_dir/$asset" -C "$tool_dir" syft
"$tool_dir/syft" --quiet agents-factory-backend:test --output "spdx-json=$output_dir/backend.spdx.json"
"$tool_dir/syft" --quiet agents-factory-control-plane:test --output "spdx-json=$output_dir/control-plane.spdx.json"

test -s "$output_dir/backend.spdx.json"
test -s "$output_dir/control-plane.spdx.json"
printf '%s\n' 'generate_sbom: backend and Control Plane SPDX artifacts created'
