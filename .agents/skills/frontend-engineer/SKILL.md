---
name: frontend-engineer
description: Enterprise Frontend Engineer profile for building React 19, TypeScript, TanStack Router/Query/Table, and Tailwind CSS v4 customer and platform dashboards in the Soopa monorepo.
---

# Enterprise Frontend Engineer Playbook

All universal monorepo laws in `.agents/AGENTS.md` apply automatically. Use this playbook when building or refactoring UI packages (`@soopa/ui`, `@soopa/edi-ui`, `@soopa/ip-ui`) and the dashboard shell (`core/ucp/apps/dashboard`).

## Monorepo Frontend Architecture & Stack

- **Runtime & Build:** React 19, TypeScript 6, Vite 8, `tsup` (workspace packages), `pnpm` (never `npm`).
- **Routing:** `@tanstack/react-router` with file-based routes (`tsr generate`). Use dedicated layout routes (`_authenticated/tenant/...`, `_authenticated/platform/...`) — never pollute `__root.tsx` with domain chrome or providers.
- **Server State & Tables:** `@tanstack/react-query` for all API fetching/caching/mutations and `@tanstack/react-table` for data tables. Keep query keys centralized and tenant-scoped; invalidate exact keys on mutation success.
- **UI Primitives & Styling (Zero Dual-Architecture):**
  - Consume shared primitives strictly from `@soopa/ui` (**Radix UI + shadcn + Tailwind CSS v4 + `lucide-react` + `sonner`**).
  - Never introduce competing primitive kits (no Base UI, MUI, AntD, Chakra) or mixing `axios` alongside native `fetch`.
  - Keep domain-specific UI components inside their bounded context package (`apps/edi/packages/ui` → `@soopa/edi-ui`, `apps/ip/packages/ui` → `@soopa/ip-ui`) and keep `core/ucp/apps/dashboard` routes thin wrappers.
- **Forms & Validation:** `react-hook-form` + `zod` v4 + `@hookform/resolvers`. Validate inputs client-side with clear field-level messages and surface structured API errors via `sonner` toasts or inline alert banners (never swallow API failures).
- **Auth & Capability Gating:** Use `react-oidc-context` (Casdoor OIDC) and capability checks from the tenant's authorization profile; never hardcode platform-admin bypasses or render sensitive controls without capability guards.

## UX & Accessibility Craft

1. **Progressive Disclosure for Complex Flows:** Surface the minimum required fields by default (e.g., 4-field < 2 min trading partner onboarding) and tuck advanced protocol tuning behind collapsible sections with safe enterprise defaults.
2. **Complete UI States:** Every data view MUST handle loading skeletons, empty states with clear primary CTAs, inline validation errors, and retryable error states.
3. **Accessibility (a11y) & Security:** Use semantic HTML, explicit `<label>`/`aria-label` associations, keyboard-accessible dialogs/menus (Radix primitives), and sanitize any untrusted HTML with `dompurify`. Never render or log secrets/private keys in the browser.

## Local Verification Gate (Before Reporting Done)

1. `pnpm --filter <pkg> lint` (`oxlint`)
2. `pnpm --filter <pkg> typecheck` (`tsr generate && tsc --noEmit`)
3. `pnpm --filter <pkg> test` (`vitest run`)
4. `pnpm --filter <pkg> build`
