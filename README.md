# Soopa Enterprise Monorepo

Welcome to the Soopa Enterprise platform! This monorepo is structured using a strict **Domain-Driven Design (DDD)** approach to scale gracefully as new applications and services are introduced.

## 🏗️ Repository Architecture

The codebase is divided into three distinct domain pillars:

- **`platform/`**: Cross-cutting foundation. Contains shared packages for observability, feature flags, global linting, etc.
- **`ucp/`**: The Unified Control Plane. The global management layer handling Tenants, Users, Billing, and global configuration.
- **`edi/`**: The Data Plane. Handles B2B EDI processing, executing inside isolated Tenant shards.

## 🚀 Getting Started

Follow these steps to set up your local development environment.

### 1. Environment Setup

Create a `.env` file at the root of the repository:

```env
# Postgres Defaults
POSTGRES_USER=zitadel
POSTGRES_PASSWORD=zitadel
POSTGRES_DB=zitadel

# Zitadel IAM
ZITADEL_MASTERKEY=a-32-byte-long-secret-key-for-zi
ZITADEL_API_TOKEN=test-token
ZITADEL_API_URL=http://ucp.localhost:8080

# Database Connections
DATABASE_URL=postgresql://ucp_admin:ucp_password@localhost:5434/ucp_global
```

*Note: Docker compose will automatically use this file. The `.env` file is also symmetrically required in the `ucp/` folder for Docker's `env_file` directive.*

### 2. Install Dependencies

We use `pnpm` workspaces to manage dependencies across all domains.

```bash
# Install node_modules across all apps and packages
pnpm install

# Build all local packages (crucial for inter-workspace dependencies like @soopa/edi-ui)
pnpm build
```

## 🛠️ Developer Commands

We use Turborepo to orchestrate commands across the monorepo. Here are the essential commands for a smooth developer experience:

### Booting the Environment

| Command | Description |
|---|---|
| **`pnpm ucp-reset`** | **The Nuke Button.** Tears down local Docker databases/LocalStack, spins them back up fresh, runs Drizzle migrations, and seeds the test Tenants. Run this when your DB state is corrupted or you change schemas. |
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

The root Platform Organization and initial Projects are managed via Terraform in the `ucp/infra/zitadel` directory.

To apply IAM changes or extract outputs into your `.env` file:
```bash
cd ucp/infra/zitadel
terraform init
terraform apply
terraform output -json
```

---

## 🧠 Development Tips

1. **Changing Shared Packages**: If you modify code in a package (like `edi/packages/ui`), the `pnpm dev` command will watch and rebuild it using `tsup --watch`. However, if you add new exports, you may need to restart the `dashboard` dev server.
2. **Ports**:
   - `5173/5174/5175`: Vite Dev Servers (Dashboard)
   - `5434`: UCP Global Postgres DB
   - `5435`: UCP Shard 1 Postgres DB
   - `4566`: LocalStack (AWS SQS, S3)
   - `8080`: Zitadel IAM
