.PHONY: build lint format typecheck test check-all dev infra-up infra-down infra-logs dev-as2 dev-worker-orchestrator dev-worker-compute dev-worker-config-sync

# ==============================================================================
# EDI AS2 - Enterprise Task Runner
# ==============================================================================

# Load variables from root .env and local .env.edi
-include ../../.env
ifneq (,$(wildcard ../../.env))
export $(shell awk -F= '/^[a-zA-Z_][a-zA-Z0-9_]*=/ {print $$1}' ../../.env)
endif

-include .env.edi
ifneq (,$(wildcard .env.edi))
export $(shell awk -F= '/^[a-zA-Z_][a-zA-Z0-9_]*=/ {print $$1}' .env.edi)
endif

build:
	@echo "=== Building Backend ==="
	uv sync --dev --all-packages
	@echo "=== Building Frontend ==="
	cd frontend/web && pnpm install && pnpm build

lint:
	@echo "=== Linting Backend ==="
	uv run ruff check packages/ apps/
	@echo "=== Linting Frontend ==="
	cd frontend/web && pnpm lint

format:
	@echo "=== Formatting Backend ==="
	uv run ruff format packages/ apps/

typecheck:
	@echo "=== Typechecking Backend ==="
	uv run mypy packages/ apps/
	@echo "=== Typechecking Frontend ==="
	cd frontend/web && pnpm tsc --noEmit

test:
	@echo "=== Testing Backend (Unit) ==="
	uv run pytest packages/ apps/ -m "not integration" --cov=.
	@echo "=== Testing Backend (Integration) ==="
	uv run pytest packages/ apps/ -m "integration" --cov=. --cov-append --cov-report=term-missing
	@echo "=== Testing Frontend ==="
	# cd frontend/web && pnpm test (enable when Vitest is scaffolded)

check-all: format lint typecheck test
	@echo "All quality checks passed!"

db-init:
	@echo "Waiting for databases to be ready..."
	@sleep 5
	@echo "Running database migrations..."
	cd packages/edi && uv run python src/edi/adapters/outbound/database/run_migrations.py
	@echo "Seeding the database..."
	cd apps/edi-as2-server && uv run python scripts/seed.py

db-reset:
	@echo "Restarting Debezium..."
	docker compose stop debezium_shard_1
	docker compose rm -f -v debezium_shard_1
	-docker volume rm apps_edi_debezium_data 2>/dev/null || true
	docker compose up -d debezium_shard_1
	@echo "Re-running migrations and seeding..."
	$(MAKE) db-init

sqs-purge:
	@echo "Purging all LocalStack SQS queues..."
	uv run python scripts/purge_sqs.py

db-sqs-reset: db-reset sqs-purge
	@echo "Database and SQS queues have been completely reset."

clear-data:
	@echo "Clearing data plane tables (edi_message, edi_json, api_gateway, outbox) and purging SQS..."
	uv run python scripts/clear_data.py --i-am-sure

seed: db-init

# --- Docker Infrastructure (Postgres, LocalStack, OTel) ---

infra-up:
	@echo "Starting local infrastructure (Background DB, S3, OTel)..."
	docker compose -f ./docker-compose.yml up -d
	@echo "\n=> Infrastructure started! Run 'make db-init' to apply migrations and seed data."

infra-down:
	@echo "Stopping local infrastructure..."
	docker compose -f ./docker-compose.yml down

infra-logs:
	@echo "Tailing infrastructure logs..."
	docker compose -f ./docker-compose.yml logs -f
