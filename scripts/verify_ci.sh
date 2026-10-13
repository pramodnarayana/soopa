#!/bin/bash
set -e

echo "🧹 Clearing caches..."
find . -name '.pytest_cache' -type d -exec rm -rf {} +
find . -name '.ruff_cache' -type d -exec rm -rf {} +
find . -name '.mypy_cache' -type d -exec rm -rf {} +

echo "🔒 Hiding .env and injecting .env.example to simulate strict CI environment..."

ENV_BACKED_UP=0
ENV_INJECTED=0

# Idempotent cleanup routine:
# 1. Disable traps to prevent re-entrant execution loops
# 2. Terminate any lingering background child processes
# 3. Restore filesystem state (.env)
# 4. Preserve original exit code
_cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  local child_pids
  child_pids=$(jobs -p 2>/dev/null || true)
  if [ -n "$child_pids" ]; then
    echo "$child_pids" | xargs kill 2>/dev/null || true
  fi

  echo ""
  echo "🔓 Restoring .env..."
  if [ "$ENV_INJECTED" -eq 1 ]; then
    rm -f .env
  fi
  if [ "$ENV_BACKED_UP" -eq 1 ] && [ -f .env.bak ]; then
    mv .env.bak .env
  fi
  echo "✅ .env restored."

  exit "$exit_code"
}

trap _cleanup EXIT INT TERM

if [ -f .env ]; then
  mv .env .env.bak
  ENV_BACKED_UP=1
fi
if [ -f .env.example ]; then
  cp .env.example .env
  ENV_INJECTED=1

  echo "🔌 Injecting Dynamic Topology Configuration into CI .env..."
  pnpm infra:sync-topology
fi

echo "🔄 Ensuring infrastructure is running (Non-Destructive)..."
pnpm infra:up

echo "✅ Running Architectural Semgrep Checks..."
uv run semgrep --config=semgrep-architecture.yml --error apps core

echo "✅ Validating Python-to-Package Dependency Sync..."
pnpm run syncpack:python:check

echo "✅ Running Typechecks..."
pnpm run typecheck

echo "✅ Running Ruff lint across full EDI surface (including e2e, workers, and apps)..."
# This runs unconditionally — bypasses turbo caching — to catch violations in all files
# including e2e tests and worker entrypoints that pnpm test excludes from execution.
uv run ruff check apps/edi

echo "✅ Running Tests (Node + Python Coverage)..."
pnpm test:node
COVERAGE_FILE=.coverage.unit CI=true pnpm cov:python

echo "✅ Running Integration Tests..."
COVERAGE_FILE=.coverage.integration CI=true pnpm test:integration

echo "✅ Test Infrastructure (Pulumi Mocks)..."
cd infra/cloud/aws && uv run pytest tests/ && cd ../../../

echo "✅ Aggregating Coverage and Enforcing Thresholds..."
./scripts/aggregate_coverage.py

echo "🎉 All CI checks passed perfectly!"
