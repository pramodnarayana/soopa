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

# --- Local Development Server ---

dev:
	@echo "Starting Frontend, API, and Worker concurrently..."
	pnpm dlx concurrently --kill-others -c "blue,magenta,cyan,yellow" -n "api,orch,comp" "make dev-api" "make dev-worker-orchestrator" "make dev-worker-compute"

dev-as2:
	@echo "Starting AS2 Server with hot-reload for local development..."
	ENVIRONMENT=development IDENTITY_AUDIENCE="api-gateway,383492001305198595,383492001305264131" uv run uvicorn as2_server.main:app --reload --host 0.0.0.0 --port 8000

dev-api:
	@echo "Starting API Gateway with hot-reload for local development..."
	ENVIRONMENT=development IDENTITY_AUDIENCE="api-gateway,383492001305198595,383492001305264131" uv run uvicorn api.main:app --reload --host 0.0.0.0 --port 8001

dev-web:
	@echo "Starting React Frontend with Vite..."
	cd frontend/web && pnpm dev

dev-worker-orchestrator:
	@echo "Starting Orchestrator Worker for local development..."
	ENVIRONMENT=development PYTHONPATH=apps/edi-worker/orchestrator/src:packages/database/src:packages/config/src:packages/pipeline/src:packages/domain/src:packages/transformer/src:packages/scheduler/src uv run python apps/edi-worker/orchestrator/src/worker/main.py

dev-worker-compute:
	@echo "Starting Compute Worker for local development..."
	ENVIRONMENT=development PYTHONPATH=apps/edi-worker/compute/src:packages/database/src:packages/config/src:packages/pipeline/src:packages/domain/src:packages/transformer/src uv run python apps/edi-worker/compute/src/compute_worker/main.py

db-init:
	@echo "Waiting for databases to be ready..."
	@sleep 5
	@echo "Running database migrations..."
	PYTHONPATH=packages/database/src:packages/config/src uv run python packages/database/src/database/run_migrations.py
	@echo "Seeding the database..."
	PYTHONPATH=packages/database/src:packages/config/src:apps/edi-worker/orchestrator/src uv run python apps/edi-as2-server/scripts/seed.py

db-reset:
	@echo "Restarting Debezium..."
	docker compose stop debezium_shard_1
	docker compose rm -f -v debezium_shard_1
	-docker volume ls -q | grep -E "debezium_data" | xargs -r docker volume rm 2>/dev/null
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
