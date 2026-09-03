#!/usr/bin/env sh

set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

fail() {
  printf '%s\n' "check_repository_security: $*" >&2
  exit 1
}

python3 infrastructure/scripts/verify_tenant_isolation_wiring.py "$0"

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

if find supabase/migrations -type f -name '*_foundation.sql' -exec \
  grep -Eni 'create[[:space:]]+extension|gen_random_uuid|uuid_generate' {} + >/dev/null; then
  fail 'foundation migrations must not install extensions or generate application UUIDs'
fi

if git grep --untracked -nEi \
  -- '(service[_-]?role|bypassrls|postgresql(\+asyncpg)?://postgres|migration[_-]?(url|password|credential))' \
  -- apps/backend/src >/dev/null; then
  fail 'backend runtime must not depend on Supabase privileged or migration credentials'
fi

if test "$#" -eq 0; then
  set -- .github/workflows/ci.yml
fi
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
  'pnpm --filter @agents-factory/control-plane exec playwright install --with-deps chromium',
  'make format-check',
  'make lint',
  'make typecheck',
  'make test-unit',
  'make eval',
  'make test-integration',
  'make test-e2e',
  'docker compose config --quiet',
  'infrastructure/scripts/test_images.sh',
  'infrastructure/scripts/generate_sbom.sh',
  'infrastructure/scripts/scan_vulnerabilities.sh',
  'make test-security'
].freeze

SECRET_EXPRESSION = /\$\{\{\s*secrets(?:\s*\.\s*[A-Za-z_][A-Za-z0-9_]*|\s*\[\s*['"][^'"]+['"]\s*\])/i

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

def walk_strings(value, path = [], &block)
  case value
  when Hash
    value.each do |key, child|
      yield key, path + ['<key>'] if key.is_a?(String)
      walk_strings(child, path + [key_name(key)], &block)
    end
  when Array
    value.each_with_index { |child, index| walk_strings(child, path + [index.to_s], &block) }
  when String
    yield value, path
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

  walk_strings(workflow) do |string, path|
    if string.match?(SECRET_EXPRESSION)
      fail("workflow secret reference is forbidden at #{workflow_path}:#{path.join('.')}")
    end
  end

  runs = []
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
      runs << command
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

  end
  unless runs == ALLOWED_RUNS
    fail("CI run commands must exactly match the locked baseline sequence: #{workflow_path}")
  end
end
RUBY

if test -d apps/backend/tests/security && \
  find apps/backend/tests/security -type f -name '*.py' -print -quit | grep -q .; then
  printf '%s\n' 'backend security suite: running'
  uv run pytest apps/backend/tests/security \
    --ignore=apps/backend/tests/security/test_tenant_isolation_matrix.py \
    --ignore=apps/backend/tests/security/test_secret_tenant_isolation.py
else
  printf '%s\n' 'backend security suite: not present'
fi

if test -d supabase/tests && find supabase/tests -type f -print -quit | grep -q .; then
  printf '%s\n' 'Supabase DB security suite: running'
  sh infrastructure/scripts/check_supabase_policy_drift.sh
  uv run --all-packages python infrastructure/scripts/run_tenant_isolation.py
  pnpm supabase test db --local supabase/tests/foundation_test.sql
  pnpm supabase db lint --local --level warning --fail-on error
  pnpm supabase db advisors --local --type all --level info --fail-on error
else
  printf '%s\n' 'Supabase DB security suite: not present'
fi

printf '%s\n' 'check_repository_security: repository and workflow security checks passed'
