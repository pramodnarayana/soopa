---
name: testing
description: Enterprise QA & Testing Engineer profile for TDD (Red-Green-Refactor), pure domain unit testing, Narrow Integration Tests with nested SAVEPOINT rollbacks, Pulumi contract testing, and Vitest UI testing.
---

# Enterprise QA & Testing Engineer Playbook

All universal monorepo laws in `.agents/AGENTS.md` apply automatically. Use this playbook when authoring, debugging, or auditing test suites across Python, AWS Pulumi IaC, and TypeScript.

## Test Pyramid & Discipline

1. **Red-Green-Refactor Cycle**:
   - Write the failing test first to prove it detects the missing feature or bug, implement the minimal clean solution to turn it green, then refactor without breaking tests.
2. **Pure Domain Unit Tests (Zero Mocks)**:
   - Test Domain Aggregates, Value Objects, parsers (e.g., X.509 metadata, Host slug extraction, RFC 1123 validators, EDI routing precedence), and `REPLICATION_GRAPH` topological sorting with real inputs and outputs — zero mocks.
3. **Narrow Integration Tests (Real Local PostgreSQL + Nested SAVEPOINTs)**:
   - Test repositories, Use Cases, FastAPI endpoints, and outbox/replication flows against real local PostgreSQL rather than mocking SQLAlchemy sessions.
   - Bind each test session to an outer transaction with `connection.begin_nested()` SAVEPOINTs and roll back completely on teardown — zero physical writes, zero `DELETE` cleanup statements.
   - Use self-contained `pytest` fixtures that explicitly create required tenants, roles, profiles, and routes; never depend on pre-seeded global `seed.py` state.
4. **AWS Pulumi IaC Contract & Runtime Tests (`infra/cloud/aws/tests/`)**:
   - Test `infra_seedwork` primitives with `pulumi.runtime.Mocks` (verifying resource graph ordering, properties, fail-fast validations, and zero bounded-context leakage into `infra_seedwork`).
   - Add stack contract tests asserting required exports, retired legacy resources, IAM least-privilege policies, and CI workflow segregation (`provision-infra.yml` vs `deploy.yml`).
5. **Frontend Behavior Tests (`vitest`)**:
   - Test user-visible behavior, form validation, error states, and capability gating using Testing Library queries (`getByRole`, `getByLabelText`) rather than brittle CSS selectors or implementation details.

## Strict Test Quality Rules

- **SRP Test Naming (CI-Enforced):** Each test verifies one focused behavioral invariant. Never write conjoined `_and_` test function names (split multi-invariant tests into separate functions).
- **Behavioral Assertions Over Call Counts:** Assert state changes, returned `Result` payloads, emitted domain events, persisted rows, or rendered UI — never write hollow `mock.assert_called_once()` coverage padding.
- **No Production Code Contamination:** Test fakes and DI overrides live strictly under `tests/` or `testing/` modules.

## Verification Commands

- **Python Unit / Integration:** `.venv/bin/pytest <test_paths>`
- **AWS Infra & Seedwork:** `.venv/bin/pytest infra/cloud/aws/tests infra/cloud/aws/packages/seedwork/tests`
- **Architecture Boundaries:** `.venv/bin/tach check`
- **Frontend:** `pnpm --filter <pkg> test`
