#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

required='README.md
docs/superpowers/specs/2026-08-12-agents-factory-master-product-architecture.md
docs/superpowers/plans/2026-08-12-agents-factory-v1.md
docs/client-onboarding-playbook.md
docs/capabilities/appointments.md
docs/capabilities/orders.md
docs/capabilities/returns-claims.md
docs/capabilities/media.md
docs/integrations/meta-whatsapp.md
docs/integrations/google-workspace.md
docs/integrations/google-sheets-orders.md
docs/integrations/woocommerce.md
docs/security/tenant-isolation.md
docs/security/secrets.md
docs/security/privacy-retention.md
docs/security/incident-handling.md
docs/operations/deploy.md
docs/operations/rollback.md
docs/operations/reconnect.md
docs/operations/dlq.md
docs/operations/restore.md
docs/operations/rotate.md
docs/operations/incident-response.md
docs/operations/go-live.md'
printf '%s\n' "$required" | while IFS= read -r path; do
  test -s "$path" || { printf '%s\n' "verify_docs: missing $path" >&2; exit 1; }
done

test ! -e docs/integrations/generic-rest.md
grep -q 'Generic REST is unavailable in v1' docs/client-onboarding-playbook.md

ruby -rpathname -ruri <<'RUBY'
root = Pathname.pwd
errors = []
(root.glob('README.md') + root.glob('docs/**/*.md') + root.glob('infrastructure/runbooks/*.md')).each do |file|
  file.read.scan(/\[[^\]]+\]\(([^)]+)\)/).flatten.each do |target|
    next if target.match?(/\A(?:https?:|mailto:|#)/)
    relative = URI.decode_www_form_component(target.split('#', 2).first)
    next if relative.empty?
    resolved = (file.dirname + relative).cleanpath
    errors << "#{file.relative_path_from(root)} -> #{target}" unless resolved.exist?
  end
end
abort("verify_docs: broken links\n#{errors.join("\n")}") unless errors.empty?
RUBY

printf '%s\n' 'verify_docs: required handbook and internal links passed'
