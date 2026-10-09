#!/usr/bin/env bash
set -e

echo "======================================================"
echo "🚀 STARTING DATABASE MIGRATIONS"
echo "======================================================"

# 1. Run Migrations for all Bounded Contexts
# Here we enforce the Enterprise Pattern: we call each context's isolated runner.
echo "Running UCP Migrations..."
python /app/core/platform/packages/database/src/database/run_migrations.py

echo "Running EDI Migrations..."
python /app/apps/edi/packages/edi/src/edi/adapters/outbound/database/run_migrations.py

echo "======================================================"
echo "🌱 STARTING DATA SEEDING"
echo "======================================================"

# 2. Run Seeding Scripts for all Bounded Contexts
echo "Seeding UCP Domain..."
python /app/core/ucp/packages/ucp/scripts/seed.py

echo "Seeding UCP Jobs..."
python /app/core/ucp/apps/ucp-jobs-worker/scripts/seed_jobs.py

echo "Seeding Identity Jobs..."
python /app/core/platform/apps/identity-jobs-worker/scripts/seed_jobs.py

echo "Seeding Notification Jobs..."
python /app/core/platform/apps/notification-jobs-worker/scripts/seed_jobs.py

echo "Seeding EDI Jobs..."
python /app/apps/edi/scripts/seed_jobs.py

echo "======================================================"
echo "✅ INITIALIZATION COMPLETE"
echo "======================================================"
