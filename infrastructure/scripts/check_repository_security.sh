#!/usr/bin/env sh

set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

fail() {
  printf '%s\n' "check_repository_security: $*" >&2
  exit 1
}

if prohibited_env_files=$(git ls-files --cached --others --exclude-standard | \
  grep -E '(^|/)\.env($|\.)' | grep -Ev '(^|/)\.env\.example$'); then
  fail "tracked environment file is forbidden: $(printf '%s\n' "$prohibited_env_files" | sed -n '1p')"
fi

if git grep --untracked -nEi \
  -- '-----BEGIN( [A-Z0-9]+)? PRIVATE KEY-----' \
  ':(exclude).env.example' >/dev/null; then
  fail 'private key material is forbidden'
fi

if git grep --untracked -nEi \
  -- '(^|[[:space:]])(API[_-]?KEY|ACCESS[_-]?KEY|CLIENT[_-]?SECRET|PRIVATE[_-]?KEY|PASSWORD|SECRET|TOKEN)[[:space:]]*[:=][[:space:]]*[^[:space:]#]+' \
  ':(exclude).env.example' >/dev/null; then
  fail 'credential-like value is forbidden'
fi

set -- .github/workflows/*.yml .github/workflows/*.yaml
ruby -rpsych - "$@" <<'RUBY'
APPROVED_ACTIONS = [
  'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1',
  'actions/setup-node@820762786026740c76f36085b0efc47a31fe5020',
  'actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',
  'astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d',
  'pnpm/action-setup@0977fd99725f1db4007ccb2928dbb4e90d06cc86'
].freeze

ALLOWED_RUNS = [
  'uv sync --locked',
  'pnpm install --frozen-lockfile',
  'make format-check',
  'make lint',
  'make typecheck',
  'make test-unit',
  'docker compose config --quiet',
  'make test-security'
].freeze

def fail(message)
  abort("check_repository_security: #{message}")
end

def key_name(key)
  key == true ? 'on' : key.to_s
end

def value_for(mapping, name)
  return mapping[name] if mapping.key?(name)
  return mapping[true] if name == 'on' && mapping.key?(true)

  nil
end

def walk(value, path = [], &block)
  case value
  when Hash
    value.each do |key, child|
      current_path = path + [key_name(key)]
      yield key_name(key), child, current_path
      walk(child, current_path, &block)
    end
  when Array
    value.each_with_index { |child, index| walk(child, path + [index.to_s], &block) }
  end
end

def contains_write?(value)
  case value
  when Hash then value.any? { |_key, child| contains_write?(child) }
  when Array then value.any? { |child| contains_write?(child) }
  when String then value.downcase.include?('write')
  else false
  end
end

workflow_paths = ARGV.select { |path| File.file?(path) }
fail('no workflow files found') if workflow_paths.empty?
workflow_paths.each do |workflow_path|
  begin
    workflow = Psych.safe_load(File.read(workflow_path), aliases: false)
  rescue Psych::Exception => error
    fail("invalid YAML in #{workflow_path}: #{error.message}")
  end
  workflow.is_a?(Hash) || fail("workflow root must be a mapping: #{workflow_path}")

  triggers = value_for(workflow, 'on')
  triggers.is_a?(Hash) || fail("workflow on must be a mapping: #{workflow_path}")
  if triggers.keys.map { |key| key_name(key) }.include?('pull_request_target')
    fail("pull_request_target is forbidden: #{workflow_path}")
  end

  permissions = value_for(workflow, 'permissions')
  unless permissions == { 'contents' => 'read' }
    fail("root permissions must be exactly contents: read: #{workflow_path}")
  end

  walk(workflow) do |key, value, path|
    if key == 'uses'
      action = value.is_a?(String) ? value : nil
      unless action&.match?(/\A[^@\s]+@[0-9a-f]{40}\z/) && APPROVED_ACTIONS.include?(action)
        fail("workflow action is not an approved full-SHA pin at #{workflow_path}:#{path.join('.')}")
      end
    end

    if key == 'run'
      command = value.is_a?(String) ? value : nil
      unless ALLOWED_RUNS.include?(command)
        fail("workflow run command is not in the locked baseline allowlist at #{workflow_path}:#{path.join('.')}")
      end
    end

    if key == 'permissions' && path.include?('jobs') && contains_write?(value)
      fail("writable job permission is forbidden at #{workflow_path}:#{path.join('.')}")
    end

    if %w[environment deployment].include?(key)
      fail("provider credentials or deployment behavior is forbidden at #{workflow_path}:#{path.join('.')}")
    end

    if key.match?(/\A(?:AWS|VERCEL|NETLIFY|CLOUDFLARE|DIGITALOCEAN|HOSTINGER)[_-]/i)
      fail("provider credential is forbidden at #{workflow_path}:#{path.join('.')}")
    end

    if value.is_a?(String) && value.match?(/\$\{\{\s*secrets\./i)
      fail("workflow secret reference is forbidden at #{workflow_path}:#{path.join('.')}")
    end
  end
end
RUBY

if test -d apps/backend/tests/security && \
  find apps/backend/tests/security -type f -name '*.py' -print -quit | grep -q .; then
  printf '%s\n' 'backend security suite: running'
  uv run pytest apps/backend/tests/security
else
  printf '%s\n' 'backend security suite: not present'
fi

if test -d supabase/tests && find supabase/tests -type f -print -quit | grep -q .; then
  printf '%s\n' 'Supabase DB security suite: running'
  pnpm supabase test db
else
  printf '%s\n' 'Supabase DB security suite: not present'
fi

printf '%s\n' 'check_repository_security: repository and workflow security checks passed'
