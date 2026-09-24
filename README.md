# Soopa Enterprise Monorepo

Welcome to the Soopa Enterprise platform! This monorepo is structured using a strict **Domain-Driven Design (DDD)** approach to scale gracefully as new applications and services are introduced.

## 🏗️ Repository Architecture

The codebase is divided into three distinct domain pillars:

- **`platform/`**: Cross-cutting foundation. Contains shared packages for observability, feature flags, global linting, etc.
- **`ucp/`**: The Unified Control Plane. The global management layer handling Tenants, Users, Billing, and global configuration.
- **`edi/`**: The Data Plane. Handles B2B EDI processing, executing inside isolated Tenant shards.

## 🚀 Getting Started (Frictionless Startup Guide)

Follow these 4 simple steps to set up your local development environment from scratch:

### 1. Environment Setup
Copy the template environment file to create your local `.env`.
```bash
cp .env.example .env
```

### 2. Install Dependencies
We use `pnpm` workspaces to manage dependencies across all domains.
```bash
pnpm install
```

### 3. Build Shared Packages
Build all local packages (crucial for inter-workspace dependencies).
```bash
pnpm build
```

### 4. Bootstrap Infrastructure
*(Make sure Docker Desktop is running first!)*
Start Zitadel, auto-generate machine tokens, provision Terraform, sync secrets to `.env`, start Postgres/LocalStack, and seed the databases — all in one command!
```bash
pnpm infra:bootstrap
```

### 5. Access the Application
Once the infrastructure is up, start the frontend and backend servers with `pnpm dev`. You can then log in using the default seeded accounts!

- **UCP Dashboard**: [http://localhost:5173](http://localhost:5173)
- **Zitadel IAM Console**: [http://ucp.localhost:8080/ui/console](http://ucp.localhost:8080/ui/console)

**Default Seeded Credentials**:
- **Platform Admin Username**: `platform.admin@flowwolf.local` (or `@soopa.local`)
- **Tenant Admin Username**: `admin@acmecorp.local`
- **Password (All Users)**: `Password1!`

## 🛠️ Developer Commands

We use Turborepo to orchestrate commands across the monorepo. Here are the essential commands for a smooth developer experience:

### Booting the Environment

| Command | Description |
|---|---|
| **`pnpm infra:bootstrap`** | ⚠️ **First-Time Developer Setup.** Run this ONLY on your very first day to start Zitadel, automatically generate your Machine PATs, run Terraform to create organizations/projects, sync secrets to `.env`, start ALL other infrastructure containers, and seed the local databases. |
| **`pnpm infra:up`** | **Start the Environment.** Non-destructively starts Postgres, LocalStack, and Zitadel, applies pending migrations, and seeds missing data. |
| **`pnpm infra:down`** | **Stop the Environment.** Safely stops all local infrastructure containers without deleting any volumes. |
| **`pnpm infra-reset`** | ⚠️ **Clean Slate Reset.** The canonical command for a fresh database or schema change. Safely uses the API to delete your app tenants in Zitadel (leaving the core Platform untouched), obliterates Postgres/LocalStack volumes, and runs `infra:up` to give you a pristine environment in seconds. **Always run this if you see `relation "..." does not exist` errors.** |
| **`pnpm ucp-reset`** | Like `infra-reset` but skips the EDI-specific `db-init`/`sqs-purge` steps. Use when working on UCP only. |
| **`pnpm dev`** | **Start the World.** Boots the UCP Dashboard UI, UCP API, EDI API, and EDI Worker all in parallel with hot-module reloading. |

### Viewing the Application

Once `pnpm dev` is running, you can access the UCP Dashboard at:
**[http://localhost:5173](http://localhost:5173)**

*(Note: If port 5173 is in use, Vite will automatically try 5174, 5175, etc. Check your terminal output for the exact URL).*

### Code Quality & Validation

| Command | Description |
|---|---|
| **`pnpm build`** | Builds all packages in the monorepo (`ui`, `database`, `identity`, etc.). Must be run if you change a shared package's exports. |
| **`pnpm typecheck`** | Runs TypeScript `tsc --noEmit` and Python `mypy` across the entire monorepo to catch type errors. |
| **`pnpm lint`** | Runs ESLint and Python `ruff check` across the monorepo. |
| **`pnpm test`** | Runs Vitest (Node) and PyTest (Python) across all domains. |
| **`pnpm knip`** | Finds unused files, dependencies, and exports in the monorepo to keep the codebase clean. |

### Database Management

| Command | Description |
|---|---|
| **`pnpm db:generate`** | Generates new Drizzle SQL migration files based on changes to your `schema.ts`. |
| **`pnpm db:migrate`** | Applies pending Drizzle migrations to your local Postgres instances. |
| **`pnpm db:seed`** | Seeds the local database with Default Tenants, Webhooks, and Event Types. |

### Infrastructure & IAM (Zitadel)

The root Platform Organization and initial Projects are managed via Terraform in the `infra/cloud/zitadel` directory.

To apply IAM changes or extract outputs into your `.env` file, simply run:
```bash
pnpm infra:bootstrap-identity
```
*(This automatically handles temporary PAT generation, Terraform initialization, apply, and `.env` synchronization).*

---

## ⚠️ Local Database Setup — Critical

The `scheduled_jobs` table and all other tables are created by Drizzle migrations. **They are NOT created automatically when you start Docker.** You MUST run migrations explicitly:

```bash
# Full reset (first-time setup or after any schema change)
pnpm infra-reset

# Or just apply pending migrations if containers are already running
pnpm db:migrate
```

**Symptoms of missing migrations:**
- `DrizzleQueryError: relation "<table>" does not exist`
- `Failed query: update "scheduled_jobs" ...`

When you see these errors, always run `pnpm infra-reset`.

---

## 🧠 Development Tips

1. **Changing Shared Packages**: If you modify code in a package (like `edi/packages/ui`), the `pnpm dev` command will watch and rebuild it using `tsup --watch`. However, if you add new exports, you may need to restart the `dashboard` dev server.
2. **Ports**:
   - `5173/5174/5175`: Vite Dev Servers (Dashboard)
   - `5434`: UCP Global Postgres DB
   - `5435`: UCP Shard 1 Postgres DB
   - `4566`: LocalStack (AWS SQS, S3)
   - `8080`: Zitadel IAM
