#!/bin/bash
set -e

echo "🧹 Clearing caches..."
find . -name '.pytest_cache' -type d -exec rm -rf {} +
find . -name '.ruff_cache' -type d -exec rm -rf {} +
find . -name '.mypy_cache' -type d -exec rm -rf {} +

echo "🔄 Resetting infrastructure..."
pnpm infra-reset

echo "🔒 Hiding .env to simulate strict CI environment..."
if [ -f .env ]; then
  mv .env .env.bak
fi

# Use a trap to ensure .env is ALWAYS restored, even if tests fail or user hits Ctrl+C
trap 'echo "🔓 Restoring .env..."; if [ -f .env.bak ]; then mv .env.bak .env; fi' EXIT

echo "✅ Running Typechecks..."
pnpm run typecheck

echo "✅ Running Tests (Node + Python)..."
pnpm test

echo "🎉 All CI checks passed perfectly!"
