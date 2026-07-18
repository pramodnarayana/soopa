# Architectural Standards
- ALWAYS default to Enterprise-Grade architectural patterns over minimum viable products (MVPs) or shortcuts.
- Use proper separation of concerns (e.g. TanStack layout routes instead of polluting `__root.tsx`).
- Implement robust error handling, proper typing, and scalable folder structures from the very first commit.
- Never use anti-patterns to save time. If a proper implementation takes more steps, take the time to do it right.

# Enterprise Coding Standards (Strictly Enforced)
- **Hexagonal Architecture**: Keep the domain isolated. Ports and Adapters must strictly separate business logic from external frameworks, APIs, and databases.
- **SOLID Principles**: Adhere to Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, and Dependency Inversion.
- **Red-Green-Refactor Cycle**: Write failing tests first, make them pass, then refactor to clean up.
- **Zero Mocks for Pure Logic**: Do not mock pure business logic. Domain models and core logic must be self-contained and testable without external mocks.
- **Narrow Integration Tests**: Stop writing "forced" unit tests with excessive mocking just to hit coverage limits. Focus on writing Narrow Integration Tests that actually connect to databases/external systems via test harnesses to test real behavior.
- **No Static Mutable Singletons**: Avoid global state. Use dependency injection to pass dependencies dynamically.
- **Infra & Business Decoupling**: Infrastructure code (AWS, SQS, DB connections) must never leak into business/domain logic.
- **No Leakage**: Data transfer objects (DTOs), API models, and ORM models must not leak across their respective boundaries. Map them appropriately.
- **DRY (Don't Repeat Yourself)**: Avoid code duplication. Extract shared logic into reusable, well-named functions/modules.

# Package Manager
- ALWAYS use `pnpm` for frontend/Node.js package management instead of `npm`. Do not use `npm install`.

# Destructive Commands
- NEVER use destructive terminal commands like `git checkout`, `git restore`, `git reset`, `git clean`, or `rm -rf` without explicitly asking for and receiving the user's permission first. Always prefer precise code-editing tools for reverting changes.
