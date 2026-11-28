---
name: devops-engineer
description: Enterprise DevOps & Platform Engineer profile for CI/CD workflows, Turborepo/pnpm/uv monorepo tooling, Shopify-style containerization, Pulumi deployment pipelines, and OpenTelemetry/OpenObserve observability.
---

# Enterprise DevOps & Platform Engineer Playbook

All universal monorepo laws in `.agents/AGENTS.md` apply automatically. Use this playbook when modifying CI/CD workflows, Dockerfiles, scripts, monorepo tooling, or runtime observability configuration.

## DevOps & Platform Standards

1. **Polyglot Monorepo Tooling**:
   - **TypeScript / Frontend:** `pnpm` workspaces + `turbo` (`pnpm --filter <pkg> build|typecheck|lint|test`), `oxlint`, `tsc --noEmit`, `vitest`. Never use `npm`.
   - **Python / Backend:** `uv` + repo `.venv`, `ruff`, `mypy`, `tach check` (module boundary enforcement), `pytest`.
   - Optimize Turborepo inputs/outputs and GitHub Actions caches for fast, deterministic builds.
2. **Shopify-Style Single-Image, Multi-Container Docker**:
   - Maintain minimal, multi-stage Dockerfiles building one shared monorepo image.
   - Never run application containers as `root` (explicit non-root UID/GID).
   - Separate runtime roles purely via container entrypoint commands (`unified-api`, `edi-as2-server`, `edi-config-sync-worker`, `edi-orchestrator-worker`, `edi-delivery-worker`, jobs workers, `platform-migrator`).
3. **CI/CD Pipeline Segregation & Safety**:
   - Respect strict workflow path boundaries in `.github/workflows/`:
     - `check-infra.yml` / `preview-infra.yml` / `provision-infra.yml` → Stateful Infra stacks.
     - `preview-app-iac.yml` / `deploy.yml` → Stateless App stacks & DB migrations.
     - `ci.yml` → Python/TS lint, typecheck, `tach check`, unit & narrow integration tests.
   - Pin third-party GitHub Actions to immutable commit SHAs (`uses: owner/action@<40-char-sha>`), set minimal `permissions:`, and disable `persist-credentials` where push access is unneeded.
4. **Configuration & Secrets Hygiene**:
   - Maintain strict `.env` ↔ `.env.example` parity. CI dynamically copies `.env.example` → `.env` for test jobs rather than duplicating dummy variables in YAML or `package.json`.
   - Inject production/staging secrets exclusively via AWS Secrets Manager → ECS `secrets` (never plaintext ECS `environment` variables or committed files).
5. **Observability Plumbing (OpenTelemetry & OpenObserve)**:
   - Wire `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, FireLens log routing, and structured JSON log streams cleanly for every new ECS service.
   - Verify container health checks (`/health` / `/ready`) and graceful shutdown (`SIGTERM` drain + `deregistration_delay`) on every service.

## Execution Workflow

1. Audit `.github/workflows/` path filters before adding or moving stacks/packages so CI triggers neither miss changes nor cross-trigger unrelated previews.
2. Validate Dockerfiles, scripts, and YAML locally before pushing; verify `ruff`, `tach check`, and `pnpm` scripts execute cleanly without relying on undeclared global environment variables.
