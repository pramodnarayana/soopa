# Technical Debt Log

This document tracks known architectural drift, quick fixes, and non-critical refactoring tasks that should be addressed in future sprints.

## [TypeScript Version Drift] Monorepo TypeScript Alignment
- **Date Added**: 2026-07-23
- **Description**: The `@soopa/dashboard` uses `typescript: ~6.0.2` while `@soopa/edi-ui` uses `typescript: ^5.4.0`. This dependency drift caused `ignoreDeprecations` mismatch issues in `tsconfig.json` during the CI build process.
- **Action Item**: Standardize the entire monorepo to use a single, unified workspace version of TypeScript (e.g. `6.0.x`). Remove the divergent `ignoreDeprecations` flags across packages once unified.

## [Python Static Typing] Enforce Strict `mypy` in CI/CD
- **Date Added**: 2026-07-23
- **Description**: Although `py.typed` markers were added to internal Python packages (`identity`, `database`, `scheduler`), the `mypy` static type checker currently only logs warnings and does not block commits or CI pipelines on failure. Furthermore, type-checking rules are not centralized.
- **Action Item**: Centrally configure `mypy` (e.g. in a workspace `pyproject.toml` or `mypy.ini`) with strict rules like `disallow_untyped_defs = true`. Update the pre-commit hooks and GitHub Actions to enforce `exit 1` on type-checking failures, preventing untyped code from reaching the main branch.

## [Authorization Architecture] Replace Magic Roles with Permission-Based Access Control (PBAC)

- **Date Added**: 2026-07-27
- **Description**: The API authorization middleware (`auth.py`) and Zero Trust ACL currently hardcode external Identity Provider (Zitadel) role names (e.g. `PlatformAdmin`) and virtual tenant IDs (`"0"`). This violates Hexagonal Architecture and creates tight coupling to external IdP nomenclature.
- **Action Item**: Implement an Anti-Corruption Layer (ACL) that dynamically maps IdP roles to canonical internal capabilities/permissions (e.g. `Permissions.SYSTEM_TENANT_BYPASS`) via configuration. Update all backend dependencies to evaluate generic capabilities rather than checking for magic strings or virtual tenant IDs.

## [UI Architecture] Consolidate UI Primitives (Radix UI vs Base UI)
- **Date Added**: 2026-07-27
- **Description**: The monorepo currently mixes two different headless UI libraries: `@soopa/edi-ui` uses Radix UI (`asChild` pattern), while `@soopa/dashboard` uses Base UI (`render` prop pattern). This library mixing led to "swallowed ref" and unclickable button bugs when the dashboard hijacked imports via Vite aliases. We have temporarily mitigated this by isolating the packages with strict ESLint boundaries and relative imports.
- **Action Item**: Standardize the entire monorepo on a single UI library (preferably Base UI, to match the newer Shadcn UI standard). Extract a unified `packages/ui` library, migrate all `@soopa/edi-ui` components to use it, and remove the Radix dependencies to reduce bundle bloat and cognitive load.
