#!/bin/bash
set -e

echo "🧹 Clearing caches..."
find . -name '.pytest_cache' -type d -exec rm -rf {} +
find . -name '.ruff_cache' -type d -exec rm -rf {} +
find . -name '.mypy_cache' -type d -exec rm -rf {} +

echo "🔄 Resetting infrastructure..."
pnpm infra-reset

echo "🔒 Hiding .env and injecting .env.example to simulate strict CI environment..."
if [ -f .env ]; then
  mv .env .env.bak
fi
if [ -f .env.example ]; then
  cp .env.example .env
fi

# Use a trap to ensure .env is ALWAYS restored, even if tests fail or user hits Ctrl+C
trap 'echo "🔓 Restoring .env..."; rm -f .env; if [ -f .env.bak ]; then mv .env.bak .env; fi' EXIT

echo "✅ Running Typechecks..."
pnpm run typecheck

echo "✅ Running Ruff lint across full EDI surface (including e2e, workers, and apps)..."
# This runs unconditionally — bypasses turbo caching — to catch violations in all files
# including e2e tests and worker entrypoints that pnpm test excludes from execution.
uv run ruff check apps/edi

echo "✅ Running Tests (Node + Python)..."
pnpm test

echo "🎉 All CI checks passed perfectly!"
