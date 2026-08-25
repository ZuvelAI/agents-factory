.DEFAULT_GOAL := help

.PHONY: help format-check lint typecheck test-unit test-integration test-security test-e2e eval build smoke

help:
	@printf '%s\n' 'Available targets: format-check lint typecheck test-unit test-integration test-security test-e2e eval build smoke'

format-check:
	@uv run --all-packages ruff format --check apps/backend/src apps/backend/tests

lint:
	@uv run --all-packages ruff check apps/backend/src apps/backend/tests

typecheck:
	@uv run --all-packages mypy apps/backend/src

test-unit:
	@uv run --all-packages pytest apps/backend/tests/unit apps/backend/tests/contract

test-integration:
	@sh infrastructure/scripts/ensure_local_database.sh
	@python3 infrastructure/scripts/run_backend_integration.py

test-security:
	@sh infrastructure/scripts/check_repository_security.sh

test-e2e:
	@printf '%s\n' 'test-e2e: no end-to-end-test-owned source files exist in Task 1.'

eval:
	@printf '%s\n' 'eval: no eval-runner-owned surface exists in Task 1.'

build:
	@printf '%s\n' 'build: no Dockerfiles are owned by Task 1.'

smoke:
	@infrastructure/scripts/smoke_compose.sh
