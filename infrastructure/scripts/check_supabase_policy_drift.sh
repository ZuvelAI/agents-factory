#!/usr/bin/env sh

set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

fail() {
  printf '%s\n' "check_supabase_policy_drift: $*" >&2
  exit 1
}

if test "$#" -eq 0; then
  set -- supabase/migrations/*_foundation.sql supabase/policies/tenant_isolation.sql
fi
test "$#" -eq 2 || \
  fail 'exactly one foundation migration and one policy fragment are required'
migration_path=$1
policy_path=$2
test -f "$migration_path" || fail 'foundation migration is missing'
test -f "$policy_path" || fail 'canonical tenant policy fragment is missing'

ruby - "$migration_path" "$policy_path" <<'RUBY'
def fail(message)
  abort("check_supabase_policy_drift: #{message}")
end

migration_path, policy_path = ARGV
migration_lines = File.readlines(migration_path)
policy = File.read(policy_path)
begin_marker = '-- BEGIN CANONICAL TENANT ISOLATION POLICIES'
end_marker = '-- END CANONICAL TENANT ISOLATION POLICIES'
begin_indexes = migration_lines.each_index.select do |index|
  migration_lines[index].chomp == begin_marker
end
end_indexes = migration_lines.each_index.select do |index|
  migration_lines[index].chomp == end_marker
end

unless begin_indexes.length == 1 && end_indexes.length == 1 && begin_indexes.first < end_indexes.first
  fail('exactly one canonical marker pair is required')
end

begin_index = begin_indexes.first
end_index = end_indexes.first
fragment = migration_lines[(begin_index + 1)...end_index].join
fail('canonical policy fragment differs from deployable migration') unless fragment == policy

outside = (migration_lines[0...begin_index] + migration_lines[(end_index + 1)..]).join
foundation_tables = %w[
  tenants
  platform_admins
  audit_events
  outbox_jobs
  job_attempts
  dead_letter_jobs
].join('|')
extra_policy = /\bcreate\s+policy\b[^;]*?\bon\s+(?:"?public"?\s*\.\s*)?"?(?:#{foundation_tables})"?\b/im
fail('foundation CREATE POLICY found outside canonical block') if outside.match?(extra_policy)

puts 'check_supabase_policy_drift: canonical policy inventory is exclusive and mirrored verbatim'
RUBY
