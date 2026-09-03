#!/usr/bin/env sh
set -eu

output_dir=${1:-artifacts/sbom}
mkdir -p "$output_dir"

tool_dir=$(mktemp -d)
trap 'rm -rf "$tool_dir"' EXIT HUP INT TERM
version=1.51.0
asset="syft_${version}_linux_amd64.tar.gz"
base_url="https://github.com/anchore/syft/releases/download/v${version}"
curl -fsSL "$base_url/syft_${version}_checksums.txt" -o "$tool_dir/checksums.txt"
printf '%s  %s\n' \
  3d85f1d0e1266cae4346514124665f10b7cefd9cce815be13921d199917e5581 \
  "$tool_dir/checksums.txt" | sha256sum --check --status
curl -fsSL "$base_url/$asset" -o "$tool_dir/$asset"
expected=$(awk -v asset="$asset" '$2 == asset {print $1}' "$tool_dir/checksums.txt")
test -n "$expected"
printf '%s  %s\n' "$expected" "$tool_dir/$asset" | sha256sum --check --status
tar -xzf "$tool_dir/$asset" -C "$tool_dir" syft
"$tool_dir/syft" --quiet agents-factory-backend:test --output "spdx-json=$output_dir/backend.spdx.json"
"$tool_dir/syft" --quiet agents-factory-control-plane:test --output "spdx-json=$output_dir/control-plane.spdx.json"

test -s "$output_dir/backend.spdx.json"
test -s "$output_dir/control-plane.spdx.json"
printf '%s\n' 'generate_sbom: backend and Control Plane SPDX artifacts created'
