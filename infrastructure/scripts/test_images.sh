#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"
backend_tag=agents-factory-backend:test
control_tag=agents-factory-control-plane:test
docker build --pull=false --build-arg SOURCE_REVISION=test -f infrastructure/docker/backend.Dockerfile -t "$backend_tag" .
docker build --pull=false --build-arg SOURCE_REVISION=test -f infrastructure/docker/control-plane.Dockerfile -t "$control_tag" .
test "$(docker image inspect --format '{{.Config.User}}' "$backend_tag")" = 'agents:agents'
test "$(docker image inspect --format '{{.Config.User}}' "$control_tag")" = 'agents:agents'
test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$backend_tag")" = test
test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$control_tag")" = test
docker image inspect --format '{{json .Config.Healthcheck.Test}}' "$backend_tag" | grep -q health/ready
docker image inspect --format '{{json .Config.Healthcheck.Test}}' "$control_tag" | grep -q health/ready
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --entrypoint python "$backend_tag" -c 'import agents_factory.main; import scheduler.worker'
docker run --rm --read-only --entrypoint node "$control_tag" -e "require('fs').accessSync('apps/control-plane/server.js')"
printf '%s\n' 'test_images: immutable labels, non-root/read-only runtime and health checks verified'
