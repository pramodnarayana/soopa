.PHONY: build lint format typecheck test check-all dev infra-up infra-down infra-logs

# ==============================================================================
# EDI AS2 - Enterprise Task Runner
# ==============================================================================

build:
	@echo "=== Building Backend ==="
	uv sync --dev --all-packages
	@echo "=== Building Frontend ==="
	cd frontend/web && pnpm install && pnpm build

lint:
	@echo "=== Linting Backend ==="
	uv run ruff check libs/ services/
	@echo "=== Linting Frontend ==="
	cd frontend/web && pnpm lint

format:
	@echo "=== Formatting Backend ==="
	uv run ruff format libs/ services/

typecheck:
	@echo "=== Typechecking Backend ==="
	uv run mypy libs/ services/
	@echo "=== Typechecking Frontend ==="
	cd frontend/web && pnpm tsc --noEmit

test:
	@echo "=== Testing Backend (Unit) ==="
	uv run pytest libs/ services/ -m "not integration" --cov=.
	@echo "=== Testing Backend (Integration) ==="
	uv run pytest libs/ services/ -m "integration" --cov=. --cov-append --cov-report=term-missing
	@echo "=== Testing Frontend ==="
	# cd frontend/web && pnpm test (enable when Vitest is scaffolded)

check-all: format lint typecheck test
	@echo "All quality checks passed!"

# --- Local Development Server ---

dev:
	@echo "Starting Frontend, API, and Worker concurrently..."
	pnpm dlx concurrently --kill-others -c "blue,magenta,cyan" -n "api,web,worker" "make dev-api" "make dev-web" "make dev-worker-orchestrator"

dev-as2:
	@echo "Starting AS2 Server with hot-reload for local development..."
	ENVIRONMENT=development uv run uvicorn as2_server.main:app --reload --host 0.0.0.0 --port 8000

dev-api:
	@echo "Starting API Gateway with hot-reload for local development..."
	ENVIRONMENT=development uv run uvicorn api.main:app --reload --host 0.0.0.0 --port 8001

dev-web:
	@echo "Starting React Frontend with Vite..."
	cd frontend/web && pnpm dev

dev-worker-orchestrator:
	@echo "Starting Orchestrator Worker for local development..."
	ENVIRONMENT=development PYTHONPATH=services/workers/orchestrator/src:libs/database/src:libs/config/src:libs/pipeline/src:libs/domain/src:libs/transformer/src uv run python services/workers/orchestrator/src/worker/main.py

dev-worker-compute:
	@echo "Starting Compute Worker for local development..."
	ENVIRONMENT=development PYTHONPATH=services/workers/compute/src:libs/database/src:libs/config/src:libs/pipeline/src:libs/domain/src:libs/transformer/src uv run python services/workers/compute/src/compute_worker/main.py

db-init:
	@echo "Waiting for databases to be ready..."
	@sleep 5
	@echo "Running database migrations..."
	PYTHONPATH=libs/database/src:libs/config/src uv run python libs/database/src/database/run_migrations.py
	@echo "Seeding the database..."
	PYTHONPATH=libs/database/src:libs/config/src uv run python services/as2_server/scripts/seed.py

db-reset:
	@echo "Wiping application databases (leaving Zitadel intact)..."
	docker compose stop postgres_global postgres_shard_1 debezium_shard_1
	docker compose rm -f -v postgres_global postgres_shard_1 debezium_shard_1
	-docker volume rm $$(docker volume ls -q | grep -E "postgres_global_data|postgres_shard_[0-9]+_data|debezium_data|localstack_data") 2>/dev/null
	@echo "Restarting application databases and Debezium..."
	docker compose up -d postgres_global postgres_shard_1 debezium_shard_1
	@echo "Waiting for databases to initialize..."
	sleep 5
	@echo "Re-running migrations and seeding..."
	$(MAKE) db-init

sqs-purge:
	@echo "Purging all LocalStack SQS queues..."
	uv run python scripts/purge_sqs.py

db-sqs-reset: db-reset sqs-purge
	@echo "Database and SQS queues have been completely reset."

clear-data:
	@echo "Clearing data plane tables (edi_message, edi_json, api_gateway, outbox) and purging SQS..."
	uv run python scripts/clear_data.py

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
