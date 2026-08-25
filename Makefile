.DEFAULT_GOAL := help

.PHONY: help format-check lint typecheck test-unit test-integration test-security test-e2e eval build smoke

help:
	@printf '%s\n' 'Available targets: format-check lint typecheck test-unit test-integration test-security test-e2e eval build smoke'

format-check:
	@printf '%s\n' 'format-check: no formatter-owned source files exist in Task 1.'

lint:
	@printf '%s\n' 'lint: no linter-owned source files exist in Task 1.'

typecheck:
	@printf '%s\n' 'typecheck: no typecheck-owned source files exist in Task 1.'

test-unit:
	@printf '%s\n' 'test-unit: no unit-test-owned source files exist in Task 1.'

test-integration:
	@printf '%s\n' 'test-integration: no integration-test-owned source files exist in Task 1.'

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
