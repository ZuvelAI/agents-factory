#!/usr/bin/env sh
set -eu

base_url=${1:?usage: smoke.sh https://environment.example}
case "$base_url" in https://*) ;; *) exit 64 ;; esac
curl --fail --silent --show-error --max-time 10 "$base_url/api/health/live" >/dev/null
curl --fail --silent --show-error --max-time 10 "$base_url/api/health/ready" >/dev/null
curl --fail --silent --show-error --max-time 10 "$base_url/health/ready" >/dev/null
printf '%s\n' 'smoke: healthy'
