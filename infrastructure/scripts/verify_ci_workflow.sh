#!/usr/bin/env sh

set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

workflow_path=${1:-.github/workflows/ci.yml}

exec ruby -rpsych - "$workflow_path" <<'RUBY'
workflow_path = ARGV.fetch(0)

APPROVED_ACTIONS = {
  'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1' => 'v7.0.1',
  'actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97' => 'v7.0.0',
  'astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d' => 'v10.0.1',
  'actions/setup-node@820762786026740c76f36085b0efc47a31fe5020' => 'v7.0.0',
  'pnpm/action-setup@0977fd99725f1db4007ccb2928dbb4e90d06cc86' => 'v6.0.10'
}.freeze

REQUIRED_RUNS = [
  'uv sync --locked',
  'pnpm install --frozen-lockfile',
  'make format-check',
  'make lint',
  'make typecheck',
  'make test-unit',
  'make eval',
  'make test-integration',
  'docker compose config --quiet',
  'make test-security'
].freeze

SECRET_EXPRESSION = /\$\{\{\s*secrets(?:\s*\.\s*[A-Za-z_][A-Za-z0-9_]*|\s*\[\s*['"][^'"]+['"]\s*\])/i

def fail(message)
  abort("verify_ci_workflow: #{message}")
end

def key_name(key)
  key == true ? 'on' : key.to_s
end

def value_for(mapping, name)
  return mapping[name] if mapping.key?(name)
  return mapping[true] if name == 'on' && mapping.key?(true)

  nil
end

def mapping!(value, label)
  value.is_a?(Hash) || fail("#{label} must be a mapping")
  value
end

def scalar!(value, label)
  value.is_a?(String) || fail("#{label} must be a scalar")
  value
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

begin
  workflow = Psych.safe_load(File.read(workflow_path), aliases: false)
rescue Psych::Exception => error
  fail("invalid YAML: #{error.message}")
end

workflow = mapping!(workflow, 'workflow root')

walk_strings(workflow) do |string, path|
  if string.match?(SECRET_EXPRESSION)
    fail("GitHub secret expression is forbidden at #{path.join('.')}")
  end
end

triggers = mapping!(value_for(workflow, 'on'), 'on')
trigger_names = triggers.keys.map { |key| key_name(key) }.sort
fail('triggers must be exactly pull_request and push') unless trigger_names == %w[pull_request push]
push = mapping!(value_for(triggers, 'push'), 'push trigger')
fail('push trigger must target only main') unless value_for(push, 'branches') == ['main']

permissions = mapping!(value_for(workflow, 'permissions'), 'root permissions')
fail('root permissions must be exactly contents: read') unless permissions == { 'contents' => 'read' }

concurrency = mapping!(value_for(workflow, 'concurrency'), 'concurrency')
fail('concurrency group must be workflow/ref') unless value_for(concurrency, 'group') == '${{ github.workflow }}-${{ github.ref }}'
fail('concurrency must cancel superseded runs') unless value_for(concurrency, 'cancel-in-progress') == true

jobs = mapping!(value_for(workflow, 'jobs'), 'jobs')
fail('workflow must contain only the ci-baseline job') unless jobs.keys.map(&:to_s) == ['ci-baseline']
job = mapping!(value_for(jobs, 'ci-baseline'), 'ci-baseline job')
fail('ci-baseline name must be stable') unless value_for(job, 'name') == 'ci-baseline'
fail('ci-baseline must run on ubuntu-24.04') unless value_for(job, 'runs-on') == 'ubuntu-24.04'
fail('ci-baseline must not override root permissions') if job.key?('permissions')

steps = value_for(job, 'steps')
fail('ci-baseline steps must be a list') unless steps.is_a?(Array)

actions = []
runs = []
steps.each_with_index do |step, index|
  step = mapping!(step, "step #{index + 1}")
  actions << scalar!(step['uses'], "step #{index + 1} uses") if step.key?('uses')
  runs << scalar!(step['run'], "step #{index + 1} run") if step.key?('run')
end

fail('CI action set must exactly match the approved pin allowlist') unless actions == APPROVED_ACTIONS.keys
fail('CI run commands must exactly match the locked baseline allowlist') unless runs == REQUIRED_RUNS

expected_with = {
  'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1' => nil,
  'actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97' => { 'python-version' => '3.12' },
  'astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d' => { 'version' => '0.12.5' },
  'actions/setup-node@820762786026740c76f36085b0efc47a31fe5020' => { 'node-version' => '24' },
  'pnpm/action-setup@0977fd99725f1db4007ccb2928dbb4e90d06cc86' => { 'version' => '11.24.0' }
}

steps.each_with_index do |step, index|
  next unless step.is_a?(Hash) && step.key?('uses')

  action = step['uses']
  fail("unapproved action at step #{index + 1}") unless expected_with.key?(action)
  expected = expected_with.fetch(action)
  actual = step['with']
  if expected.nil?
    fail("unexpected action inputs at step #{index + 1}") if actual
  else
    fail("incorrect action inputs at step #{index + 1}") unless actual == expected
  end
end

puts 'verify_ci_workflow: CI workflow contract passed'
RUBY
