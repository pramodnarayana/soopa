#!/bin/bash
set -e

echo "🧹 Clearing caches..."
find . -name '.pytest_cache' -type d -exec rm -rf {} +
find . -name '.ruff_cache' -type d -exec rm -rf {} +
find . -name '.mypy_cache' -type d -exec rm -rf {} +

echo "🔄 Resetting infrastructure..."
pnpm infra-reset

echo "🔒 Hiding .env and injecting .env.example to simulate strict CI environment..."

ENV_BACKED_UP=0
ENV_INJECTED=0

# Use a trap to ensure .env is ALWAYS restored, even if tests fail or user hits Ctrl+C
trap 'echo "🔓 Restoring .env..."; [ "$ENV_INJECTED" -eq 1 ] && rm -f .env; [ "$ENV_BACKED_UP" -eq 1 ] && mv .env.bak .env' EXIT

if [ -f .env ]; then
  mv .env .env.bak
  ENV_BACKED_UP=1
fi
if [ -f .env.example ]; then
  cp .env.example .env
  ENV_INJECTED=1
fi

echo "✅ Running Typechecks..."
pnpm run typecheck

echo "✅ Running Ruff lint across full EDI surface (including e2e, workers, and apps)..."
# This runs unconditionally — bypasses turbo caching — to catch violations in all files
# including e2e tests and worker entrypoints that pnpm test excludes from execution.
uv run ruff check apps/edi

echo "✅ Running Tests (Node + Python)..."
pnpm test

echo "✅ Running Integration Tests..."
pnpm test:integration

echo "🎉 All CI checks passed perfectly!"
