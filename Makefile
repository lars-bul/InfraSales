SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

PNPM := pnpm --dir frontend
IMAGE := infrasales:local
TRIVY := docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache \
	-v "$(CURDIR)":/out aquasec/trivy:0.75.0@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa
PROFILE ?= dev
RUN = uv run --env-file profiles/$(PROFILE).env

.PHONY: help install profiles dev fmt lint typecheck test test-pg check ci audit audit-image sbom \
	migrate api-types image up down prod-up prod-down clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-z0-9-]+:.*## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install dependencies and git hooks
	uv sync --locked
	$(PNPM) install --frozen-lockfile
	uv run pre-commit install --install-hooks

profiles: ## Copy each profiles/*.env.example to its .env, keeping those already there
	@for example in profiles/*.env.example; do \
		target=$${example%.example}; \
		if [ -e "$$target" ]; then echo "kept    $$target"; \
		else cp "$$example" "$$target"; echo "created $$target: fill it in"; fi; \
	done

profiles/%.env:
	@echo "profiles/$*.env is missing: run \`make profiles\`, then fill it in" >&2; exit 1

dev: profiles/$(PROFILE).env ## The app on http://localhost:5173 (PROFILE=dev): Vite and FastAPI, reloading on code changes
	mkdir -p data
	$(RUN) infrasales migrate
	trap 'kill 0' EXIT; $(RUN) infrasales web --reload & $(RUN) $(PNPM) dev & wait -n

fmt: ## Format and apply safe lint fixes
	uv run ruff check --fix .
	uv run ruff format .
	$(PNPM) format

lint: ## Lint and format check (ruff, biome), generated API client current
	uv run ruff check .
	uv run ruff format --check .
	$(PNPM) lint

typecheck: ## Strict type checks (pyright, tsc)
	uv run pyright
	$(PNPM) typecheck

test: lint typecheck ## Quality gates, then all tests with 85 % coverage (pytest, vitest)
	uv run coverage run -m pytest
	uv run coverage report
	$(PNPM) test

.PHONY: e2e
e2e: ## Browser tests (Chromium) against the production build behind FastAPI [E2E_PORT=8765]
	$(PNPM) exec playwright install --only-shell chromium
	$(PNPM) e2e

TEST_PG = postgresql+psycopg://infrasales_ROLE@127.0.0.1:5432/infrasales_test

test-pg: ## Backend tests against PostgreSQL 18 (Docker): roles, concurrency, migrations
	docker compose up --detach --wait postgres
	TEST_DATABASE_URL=$(subst ROLE,owner:owner,$(TEST_PG)) \
	TEST_APP_DATABASE_URL=$(subst ROLE,app:app,$(TEST_PG)) \
	TEST_RETENTION_DATABASE_URL=$(subst ROLE,retention:retention,$(TEST_PG)) \
	uv run pytest

check: ## Every pre-commit hook on all files
	uv run pre-commit run --all-files

ci: check test test-pg audit image audit-image ## Everything a pipeline gates on

audit: ## Known vulnerabilities in uv.lock and pnpm-lock.yaml
	uv audit --locked --preview-features audit-command
	$(PNPM) audit

audit-image: ## Vulnerabilities in the image, OS packages included (HIGH and CRITICAL fail)
	$(TRIVY) image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed $(IMAGE)

sbom: ## CycloneDX SBOM of the image -> sbom.cdx.json
	$(TRIVY) image --format cyclonedx --output /out/sbom.cdx.json $(IMAGE)

migrate: ## New migration from model changes: make migrate [m="add source table"]
	@tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	export DATABASE_URL="sqlite+aiosqlite:///$$tmp/schema.db" LOG_FORMAT=console && \
	uv run infrasales migrate && \
	uv run alembic revision --autogenerate $(if $(m),-m "$(m)")

api-types: ## Regenerate the API contract (openapi.json) and the UI's generated API client
	uv run infrasales openapi > openapi.json
	$(PNPM) api-types

image: ## Build the production image
	docker build --tag $(IMAGE) --build-arg REVISION=$$(git rev-parse --short HEAD 2>/dev/null || echo dev) .

up: image profiles/$(or $(filter-out dev,$(PROFILE)),stack).env ## The local container stack on http://localhost:8000
	docker compose up --detach --wait

down: ## Stop the local container stack (the database volume stays)
	docker compose --profile mail --profile otel down

prod-up: image profiles/prod.env ## Production: migrate, the app, retention (compose.prod.yaml)
	docker compose -f compose.prod.yaml up --detach --wait

prod-down: ## Stop the production services
	docker compose -f compose.prod.yaml down

clean: ## Remove caches and build output
	rm -rf .pytest_cache .ruff_cache .coverage frontend/dist frontend/coverage sbom.cdx.json \
		frontend/test-results frontend/playwright-report frontend/e2e/.auth
