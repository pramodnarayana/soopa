.PHONY: build lint format typecheck test check-all dev infra-up infra-down infra-logs

# ==============================================================================
# EDI AS2 - Enterprise Task Runner
# ==============================================================================

build:
	@echo "Installing dependencies and preparing workspace..."
	uv sync --dev --all-packages

lint:
	@echo "Running ruff linter..."
	uv run ruff check libs/ services/

format:
	@echo "Running ruff formatter..."
	uv run ruff format libs/ services/

typecheck:
	@echo "Running mypy strict type checking..."
	uv run mypy libs/ services/

test:
	@echo "Running pytest suite..."
	uv run pytest libs/ services/ --cov=. --cov-report=term-missing

check-all: format lint typecheck test
	@echo "All quality checks passed!"

# --- Local Development Server ---

dev:
	@echo "Starting AS2 Server with hot-reload for local development..."
	uv run uvicorn as2_server.main:app --reload --port 8000

seed:
	@echo "Seeding the database..."
	uv run python services/as2_server/scripts/seed.py

# --- Docker Infrastructure (Postgres, LocalStack, OTel) ---

infra-up:
	@echo "Starting local infrastructure (Background DB, S3, OTel)..."
	docker compose -f ../docker-compose.yml up -d

infra-down:
	@echo "Stopping local infrastructure..."
	docker compose -f ../docker-compose.yml down

infra-logs:
	@echo "Tailing infrastructure logs..."
	docker compose -f ../docker-compose.yml logs -f
