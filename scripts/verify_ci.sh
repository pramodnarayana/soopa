#!/usr/bin/env bash
set -euo pipefail

MODE="full"
BASE_REF=""
CLEAN_CACHES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --affected)
      MODE="affected"
      shift
      ;;
    --full)
      MODE="full"
      shift
      ;;
    --base-ref)
      BASE_REF="${2:-}"
      shift 2
      ;;
    --clean-caches)
      CLEAN_CACHES=1
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: ./scripts/verify_ci.sh [--affected | --full] [--base-ref <ref>] [--clean-caches]" >&2
      exit 2
      ;;
  esac
done

export TURBO_CONCURRENCY="${TURBO_CONCURRENCY:-4}"

if [[ "$CLEAN_CACHES" -eq 1 ]]; then
  echo "🧹 Clearing tool caches (--clean-caches)..."
  find . \( -name '.pytest_cache' -o -name '.ruff_cache' -o -name '.mypy_cache' \) -type d -prune -exec rm -rf {} +
fi

# Remove stale per-package coverage artifacts so aggregate_coverage.py evaluates only current-run scope
find apps core -maxdepth 5 \( -name '.coverage' -o -name '.coverage.*' \) -delete 2>/dev/null || true

RESOLVED_MODE="full"
RESOLVED_BASE=""
if [[ "$MODE" == "affected" ]]; then
  SCOPE_ARGS=(--print-scope)
  if [[ -n "$BASE_REF" ]]; then
    SCOPE_ARGS+=(--base-ref "$BASE_REF")
  fi
  read -r RESOLVED_MODE RESOLVED_BASE < <(uv run python infra/local/scripts/run_in_test_env.py "${SCOPE_ARGS[@]}")
  if [[ "$RESOLVED_MODE" == "affected_empty" ]]; then
    echo "✨ No changes detected relative to ${RESOLVED_BASE}. Skipping redundant CI checks."
    exit 0
  fi
fi

if [[ "$RESOLVED_MODE" == "affected" ]]; then
  echo "🎯 Running graph-aware CI verification for packages affected since ${RESOLVED_BASE:0:12} (concurrency=${TURBO_CONCURRENCY})..."
else
  echo "🔒 Running full clean-room CI verification (concurrency=${TURBO_CONCURRENCY}, .env untouched)..."
fi

echo "🔄 Ensuring local infrastructure containers are healthy (non-destructive)..."
INFRA_SERVICES=()
while IFS= read -r svc; do
  case "$svc" in
    postgres_global|*_postgres_shard|localstack|sftp)
      INFRA_SERVICES+=("$svc")
      ;;
  esac
done < <(docker compose --env-file .env.example --env-file versions.env config --services)

if [[ "${#INFRA_SERVICES[@]}" -gt 0 ]]; then
  docker compose --env-file .env.example --env-file versions.env up -d --wait "${INFRA_SERVICES[@]}"
fi

echo "🧪 Ensuring isolated *_test PostgreSQL databases are provisioned and synced..."
uv run python infra/local/scripts/run_in_test_env.py --hermetic --env-file .env.example -- true

echo "✅ Running Architectural Semgrep Checks..."
SEMGREP_EXCLUDES=(--exclude node_modules --exclude .venv --exclude dist --exclude build)
SEMGREP_CONFIG_CHANGED=0
if [[ "$MODE" == "affected" ]] && [[ -n "$RESOLVED_BASE" ]]; then
  if git diff --name-only "${RESOLVED_BASE}..HEAD" | grep -qE '^(semgrep-architecture\.yml|\.semgrep/)'; then
    SEMGREP_CONFIG_CHANGED=1
  fi
fi

if [[ "$MODE" == "affected" ]] && [[ -n "$RESOLVED_BASE" ]] && [[ "$SEMGREP_CONFIG_CHANGED" -eq 0 ]]; then
  SEMGREP_TARGETS=()
  while IFS= read -r changed_file; do
    if [[ -f "$changed_file" ]] && [[ "$changed_file" == apps/* || "$changed_file" == core/* ]]; then
      SEMGREP_TARGETS+=("$changed_file")
    fi
  done < <(git diff --name-only "${RESOLVED_BASE}..HEAD")
  if [[ "${#SEMGREP_TARGETS[@]}" -gt 0 ]]; then
    uv run --with "semgrep==1.165.0" semgrep --config=semgrep-architecture.yml --config=.semgrep/enterprise-rules.yml "${SEMGREP_EXCLUDES[@]}" --error "${SEMGREP_TARGETS[@]}"
  fi
else
  uv run --with "semgrep==1.165.0" semgrep --config=semgrep-architecture.yml --config=.semgrep/enterprise-rules.yml "${SEMGREP_EXCLUDES[@]}" --error apps core
fi

echo "✅ Validating Python-to-Package Dependency Sync & Module Boundaries..."
pnpm run syncpack:python:check
uv run tach check

echo "✅ Running Ruff & Mypy across workspace source trees and root scripts..."
uv run ruff check apps core infra/local/scripts scripts
uv run ruff format --check apps core infra/local/scripts scripts
uv run mypy --explicit-package-bases infra/local/scripts/run_in_test_env.py infra/local/scripts/ensure_test_databases.py infra/local/scripts/sync_topology.py scripts/aggregate_coverage.py

if [[ "$RESOLVED_MODE" == "affected" ]] && [[ -n "$RESOLVED_BASE" ]]; then
  AFFECTED_FILTER="--filter=...[${RESOLVED_BASE}]"

  echo "✅ Running Affected Typechecks & Lints..."
  pnpm turbo run typecheck --concurrency="${TURBO_CONCURRENCY}" "$AFFECTED_FILTER"
  pnpm turbo run typecheck:tests --concurrency="${TURBO_CONCURRENCY}" "$AFFECTED_FILTER"
  pnpm turbo run lint --concurrency="${TURBO_CONCURRENCY}" "$AFFECTED_FILTER"

  echo "✅ Running Affected Unit Tests (Node + Python Coverage in hermetic .env.example)..."
  uv run python infra/local/scripts/run_in_test_env.py --hermetic --env-file .env.example --skip-db-ensure -- \
    pnpm test:node "$AFFECTED_FILTER"

  # Match exact package scope of root `cov:python` when intersecting with Turbo's affected graph
  COV_AFFECTED_EXCLUDES=(
    --filter="!@soopa/seedwork"
    --filter="!@soopa/outbox"
    --filter="!@soopa/pubsub"
    --filter="!@soopa/orchestration"
    --filter="!@soopa/edi-secrets-sidecar"
    --filter="!@soopa/unified-api"
    --filter="!@soopa/dummy-pykcs11"
  )

  COVERAGE_FILE=.coverage.unit CI=true \
    uv run python infra/local/scripts/run_in_test_env.py --hermetic --env-file .env.example --skip-db-ensure -- \
    pnpm turbo run cov --env-mode=loose --concurrency="${TURBO_CONCURRENCY}" "$AFFECTED_FILTER" \
      "${COV_AFFECTED_EXCLUDES[@]}"

  echo "✅ Running Affected Integration Tests (isolated *_test databases)..."
  COVERAGE_FILE=.coverage.integration CI=true \
    uv run python infra/local/scripts/run_in_test_env.py --hermetic --env-file .env.example --skip-db-ensure -- \
    pnpm turbo run test:integration --env-mode=loose --concurrency="${TURBO_CONCURRENCY}" "$AFFECTED_FILTER" \
      --filter="!@soopa/pubsub"
else
  echo "✅ Running Full Typechecks & Lints..."
  pnpm turbo run typecheck --concurrency="${TURBO_CONCURRENCY}"
  pnpm turbo run typecheck:tests --concurrency="${TURBO_CONCURRENCY}"
  pnpm turbo run lint --concurrency="${TURBO_CONCURRENCY}"

  echo "✅ Running Full Unit Tests (Node + Python Coverage in hermetic .env.example)..."
  uv run python infra/local/scripts/run_in_test_env.py --hermetic --env-file .env.example --skip-db-ensure -- \
    pnpm test:node

  COVERAGE_FILE=.coverage.unit CI=true \
    uv run python infra/local/scripts/run_in_test_env.py --hermetic --env-file .env.example --skip-db-ensure -- \
    pnpm cov:python --env-mode=loose --concurrency="${TURBO_CONCURRENCY}"

  echo "✅ Running Full Integration Tests (isolated *_test databases)..."
  COVERAGE_FILE=.coverage.integration CI=true \
    uv run python infra/local/scripts/run_in_test_env.py --hermetic --env-file .env.example --skip-db-ensure -- \
    pnpm turbo run test:integration --env-mode=loose --concurrency="${TURBO_CONCURRENCY}" \
      --filter="!@soopa/pubsub"
fi

echo "✅ Aggregating Coverage and Enforcing Thresholds..."
./scripts/aggregate_coverage.py

echo "🎉 All CI checks passed! (.env and live development databases untouched)"
