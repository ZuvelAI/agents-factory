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

def mask_non_executable_sql(sql, visible_identifiers)
  masked = +''
  index = 0
  state = :normal
  block_depth = 0
  dollar_tag = nil

  while index < sql.length
    case state
    when :normal
      if sql[index, 2] == '--'
        masked << '  '
        index += 2
        state = :line_comment
      elsif sql[index, 2] == '/*'
        masked << '  '
        index += 2
        block_depth = 1
        state = :block_comment
      elsif sql[index] == '"'
        identifier = +''
        cursor = index + 1
        terminated = false
        while cursor < sql.length
          if sql[cursor, 2] == '""'
            identifier << '"'
            cursor += 2
          elsif sql[cursor] == '"'
            cursor += 1
            terminated = true
            break
          else
            identifier << sql[cursor]
            cursor += 1
          end
        end
        segment = sql[index...cursor]
        if terminated && visible_identifiers.include?(identifier)
          masked << segment
        else
          masked << segment.each_char.map { |character| character == "\n" ? "\n" : ' ' }.join
        end
        index = cursor
      elsif sql[index] == "'"
        masked << ' '
        escape_prefix = index.positive? && sql[index - 1].match?(/[eE]/) &&
          (index == 1 || !sql[index - 2].match?(/[A-Za-z0-9_$]/))
        index += 1
        state = escape_prefix ? :escape_single_quote : :single_quote
      elsif (index.zero? || !sql[index - 1].match?(/[A-Za-z0-9_$]/)) &&
          (match = sql[index..].match(/\A\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$/))
        dollar_tag = match[0]
        masked << (' ' * dollar_tag.length)
        index += dollar_tag.length
        state = :dollar_quote
      else
        masked << sql[index]
        index += 1
      end
    when :line_comment
      if sql[index] == "\n"
        masked << "\n"
        state = :normal
      else
        masked << ' '
      end
      index += 1
    when :block_comment
      if sql[index, 2] == '/*'
        masked << '  '
        index += 2
        block_depth += 1
      elsif sql[index, 2] == '*/'
        masked << '  '
        index += 2
        block_depth -= 1
        state = :normal if block_depth.zero?
      else
        masked << (sql[index] == "\n" ? "\n" : ' ')
        index += 1
      end
    when :single_quote
      if sql[index, 2] == "''"
        masked << '  '
        index += 2
      elsif sql[index] == "'"
        masked << ' '
        index += 1
        state = :normal
      else
        masked << (sql[index] == "\n" ? "\n" : ' ')
        index += 1
      end
    when :escape_single_quote
      if sql[index, 2] == "''" || sql[index] == '\\'
        width = sql[index, 2] == "''" ? 2 : [2, sql.length - index].min
        masked << (' ' * width)
        index += width
      elsif sql[index] == "'"
        masked << ' '
        index += 1
        state = :normal
      else
        masked << (sql[index] == "\n" ? "\n" : ' ')
        index += 1
      end
    when :dollar_quote
      if sql[index, dollar_tag.length] == dollar_tag
        masked << (' ' * dollar_tag.length)
        index += dollar_tag.length
        state = :normal
      else
        masked << (sql[index] == "\n" ? "\n" : ' ')
        index += 1
      end
    end
  end

  masked
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
foundation_table_names = %w[
  tenants
  platform_admins
  audit_events
  outbox_jobs
  job_attempts
  dead_letter_jobs
]
foundation_tables = foundation_table_names.join('|')
executable_outside = mask_non_executable_sql(
  outside,
  ['public'] + foundation_table_names
)
policy_mutation = /\b(?:create|alter|drop)\s+policy\b[^;]*?\bon\s+(?:only\s+)?(?:(?:"public"|public)\s*\.\s*)?(?:"(?:#{foundation_tables})"|(?:#{foundation_tables}))(?![A-Za-z0-9_$])/im
if executable_outside.match?(policy_mutation)
  fail('foundation policy authorization mutation found outside canonical block')
end

puts 'check_supabase_policy_drift: canonical policy inventory is exclusive and mirrored verbatim'
RUBY
