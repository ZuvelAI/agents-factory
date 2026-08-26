#!/usr/bin/env sh

set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

fail() {
  printf '%s\n' "check_supabase_policy_drift: $*" >&2
  exit 1
}

if test "$#" -eq 0; then
  set -- supabase/migrations/*[0-9]_foundation.sql \
    supabase/policies/tenant_isolation.sql
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

def identifier_character?(character)
  character && character.match?(/[A-Za-z0-9_$]/)
end

def skip_sql_spacing(sql, index)
  loop do
    previous = index
    index += 1 while index < sql.length && sql[index].match?(/\s/)

    if sql[index, 2] == '--'
      index += 2
      index += 1 while index < sql.length && sql[index] != "\n"
    elsif sql[index, 2] == '/*'
      index += 2
      depth = 1
      while index < sql.length && depth.positive?
        if sql[index, 2] == '/*'
          depth += 1
          index += 2
        elsif sql[index, 2] == '*/'
          depth -= 1
          index += 2
        else
          index += 1
        end
      end
    end

    break if index == previous
  end
  index
end

def unicode_escape_clause(sql, index)
  clause_start = skip_sql_spacing(sql, index)
  keyword = sql[clause_start, 7]
  return ['\\', index] unless keyword&.casecmp?('UESCAPE')

  keyword_end = clause_start + 7
  return ['\\', index] if identifier_character?(sql[keyword_end])

  literal_start = skip_sql_spacing(sql, keyword_end)
  return ['\\', index] unless sql[literal_start] == "'"

  escape_character = sql[literal_start + 1]
  return ['\\', index] unless escape_character && sql[literal_start + 2] == "'"

  [escape_character, literal_start + 3]
end

def decode_unicode_identifier(identifier, escape_character)
  decoded = +''
  index = 0
  while index < identifier.length
    unless identifier[index] == escape_character
      decoded << identifier[index]
      index += 1
      next
    end

    if identifier[index + 1] == escape_character
      decoded << escape_character
      index += 2
      next
    end

    if identifier[index + 1] == '+'
      digits = identifier[index + 2, 6]
      width = 8
    else
      digits = identifier[index + 1, 4]
      width = 5
    end
    return nil unless digits&.match?(/\A[0-9A-Fa-f]{#{width == 8 ? 6 : 4}}\z/)

    codepoint = digits.to_i(16)
    return nil if codepoint > 0x10ffff || (0xd800..0xdfff).cover?(codepoint)

    decoded << codepoint.chr(Encoding::UTF_8)
    index += width
  end
  decoded
rescue RangeError
  nil
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
        unicode_identifier = index >= 2 && sql[index - 2, 2]&.casecmp?('U&') &&
          (index == 2 || !identifier_character?(sql[index - 3]))
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

        segment_start = unicode_identifier ? index - 2 : index
        escape_character = '\\'
        if terminated && unicode_identifier
          escape_character, cursor = unicode_escape_clause(sql, cursor)
          identifier = decode_unicode_identifier(identifier, escape_character)
          masked.slice!(-2, 2)
        end

        segment = sql[segment_start...cursor]
        if terminated && identifier && visible_identifiers.include?(identifier)
          masked << %Q{"#{identifier}"}
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
