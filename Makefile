.DEFAULT_GOAL := help

.PHONY: help format-check lint typecheck test-unit test-integration test-security test-secrets test-tenant-isolation test-e2e eval build smoke docs

help:
	@printf '%s\n' 'Available targets: format-check lint typecheck test-unit test-integration test-security test-secrets test-tenant-isolation test-e2e eval build smoke'

format-check:
	@uv run --all-packages ruff format --check apps/backend/src apps/backend/tests workers evals
	@pnpm run format:check

lint:
	@uv run --all-packages ruff check apps/backend/src apps/backend/tests workers evals
	@pnpm run lint

typecheck:
	@uv run --all-packages mypy apps/backend/src evals workers/agent-worker/src workers/knowledge-worker/src workers/outbound-worker/src workers/scheduler/src
	@pnpm run typecheck

test-unit:
	@uv run --all-packages pytest apps/backend/tests/unit apps/backend/tests/contract
	@pnpm run test:unit

test-integration:
	@sh infrastructure/scripts/ensure_local_database.sh
	@python3 infrastructure/scripts/run_backend_integration.py

test-security:
	@sh infrastructure/scripts/check_repository_security.sh

test-secrets:
	@uv run --all-packages pytest apps/backend/tests/security/test_secret_envelope.py apps/backend/tests/security/test_secret_redaction.py

test-tenant-isolation:
	@uv run --all-packages python infrastructure/scripts/run_tenant_isolation.py

test-e2e:
	@pnpm run test:e2e

eval:
	@uv run --all-packages python evals/run_local.py \
		--cases evals/cases \
		--output evals/results/latest.json \
		--seed 20260827

build:
	@infrastructure/scripts/test_images.sh

smoke:
	@infrastructure/scripts/smoke_compose.sh

docs:
	@infrastructure/scripts/verify_docs.sh
