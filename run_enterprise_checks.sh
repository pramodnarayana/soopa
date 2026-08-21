#!/bin/sh
set -e

echo "[1/8] Formatting Codebase"
pnpm turbo format

echo "[2/8] Pre-commit Hooks (All Files)"
uvx pre-commit==4.3.0 run --all-files

echo "[3/8] Typechecking"
pnpm turbo typecheck typecheck:tests

echo "[4/8] Linting"
pnpm turbo lint

echo "[5/8] Dead Code Analysis"
pnpm deadcode
pnpm turbo deadcode:deptry

echo "[6/8] Unit & Integration Tests"
export DATABASE_URL="postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
export SHARD_1_URL="postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
export TESTCONTAINERS_RYUK_DISABLED=true
pnpm turbo test

echo "[7/8] Build"
pnpm turbo build

echo "[8/8] Done! All enterprise checks passed."
