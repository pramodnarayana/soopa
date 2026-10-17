# Soopa Enterprise Monorepo

Welcome to the Soopa Enterprise platform! This monorepo is structured using a strict **Domain-Driven Design (DDD)** modular monolith architecture to scale gracefully as new applications and services are introduced.

## 🏗️ Repository Architecture

The codebase is divided into three distinct domain pillars:

- **`platform/`**: Cross-cutting foundation. Contains shared packages for database engine pooling, observability, messaging, outbox, and global security.
- **`ucp/`**: The Unified Control Plane. The global management layer handling Tenants, Users, Billing, and global configuration.
- **`edi/`**: The Data Plane. Handles high-throughput B2B EDI transactions and partner integrations, executing inside isolated Tenant shards.

---

## 📋 Prerequisites

Before setting up the repository on a fresh laptop, ensure you have the following installed:

1. **Node.js**: `v20.x` or higher
2. **pnpm**: `v9.x` or higher (`corepack enable` or `npm install -g pnpm`)
3. **Python**: `3.12` or higher
4. **uv**: `>= 0.11.24` (Astral's high-performance Python package manager: `curl -LsSf https://astral.sh/uv/install.sh | sh` or `brew install uv`)
5. **Docker Desktop**: With Docker Compose v2 enabled and running

> ℹ️ **Note**: Neither Pulumi nor Terraform is required on your local machine for day-to-day development. Local Zitadel IAM and Docker services are bootstrapped entirely via pure Python REST automation!

---

## 🚀 Getting Started (Frictionless Startup Guide)

Follow these 5 simple steps to set up your local development environment from scratch:

### 1. Environment Setup
Copy the template environment file to create your local `.env`.
```bash
cp .env.example .env
```

### 2. Install Dependencies
Install dependencies for both TypeScript and Python workspaces:
```bash
# Install Node.js workspace dependencies
pnpm install

# Synchronize all Python workspaces and virtual environments
uv sync --all-packages
```

### 3. Build Shared Packages
Build all local packages (crucial for inter-workspace dependencies).
```bash
pnpm build
```

### 4. Bootstrap Infrastructure
*(Make sure Docker Desktop is running first!)*

Run the bootstrap command:
```bash
pnpm bootstrap
```
This single command automates the entire local stack:
- Cleans and prepares OpenAS2 runtime directories
- Boots Zitadel IAM in Docker
- Provisions organizations, project roles, machine keys, and OIDC apps via pure Python REST API
- Synchronizes credentials and client IDs directly to `.env`
- Starts PostgreSQL (Global & EDI Shard), LocalStack (AWS SQS/S3), and SFTP
- Executes platform & EDI database migrations (`platform_migrator` with Alembic)
- Seeds initial administrative and tenant data
- Initializes OpenAS2 and EDI SQS queues
- Prints all seeded credentials and dashboard URLs

### 5. Start Development
Launch all frontend and backend services in parallel with hot-reloading:
```bash
pnpm dev
```

Once running, access the services in your browser:
- **UCP Dashboard**: [http://localhost:5173](http://localhost:5173)
- **Unified API Docs**: [http://localhost:3000/docs](http://localhost:3000/docs)
- **Zitadel IAM Console**: [http://ucp.localhost:8080/ui/console](http://ucp.localhost:8080/ui/console)

**Default Seeded Credentials**:
- **Platform Admin Username**: `admin@flowwolf.io`
- **Platform Admin Password**: `Password1!`
- **Tenant Default Password**: `Password1!` (Assigned to all seeded tenant users)
- **Zitadel IAM Console Username**: `zitadel-admin@zitadel.ucp.localhost`
- **Zitadel IAM Console Password**: `Password1!`

> 💡 **Tip**: Run `pnpm credentials` (or `pnpm creds`) anytime to re-display all local developer credentials and service URLs.

---

## 🛠️ Developer Commands

We use Turborepo to orchestrate commands across the monorepo. Here are the essential commands:

### Booting & Managing Infrastructure

| Command | Description |
|---|---|
| **`pnpm bootstrap`** | ⚠️ **First-Time Developer Setup.** Runs full infrastructure bootstrap: Zitadel API provisioning, `.env` sync, PostgreSQL, LocalStack, Alembic migrations, database seeds, OpenAS2, and prints login credentials. |
| **`pnpm dev`** | **Start the World.** Boots the UCP Dashboard UI, backend APIs, and workers in parallel with hot-module reloading. |
| **`pnpm up`** | Starts infrastructure and services non-destructively. |
| **`pnpm down`** | Safely stops all local infrastructure containers without deleting database volumes. |
| **`pnpm infra-reset`** | ⚠️ **Clean Slate Reset.** Cleans tenant data in Zitadel, resets Postgres/LocalStack volumes, reapplies all migrations, and reseeds initial data. Use this whenever you encounter database schema mismatches. |
| **`pnpm credentials`** | Prints all developer credentials, admin logins, and service URLs. |

### Code Quality & Validation

| Command | Description |
|---|---|
| **`pnpm build`** | Builds all packages in the monorepo (`ui`, `database`, `identity`, etc.). Run after updating shared package exports. |
| **`pnpm typecheck`** | Runs TypeScript `tsc --noEmit` and Python `mypy` across the entire monorepo. |
| **`pnpm lint`** | Runs ESLint and Python `ruff check` across the monorepo. |
| **`pnpm test`** | Runs Vitest (Node) and PyTest (Python) across all domains. |
| **`pnpm knip`** | Finds unused files, dependencies, and exports to keep the monorepo clean. |

### Database Management & Migrations

Database migrations are managed via **Alembic** and SQLAlchemy through the unified `platform_migrator` package:

| Command | Description |
|---|---|
| **`pnpm db:migrate`** | Runs platform migrations, seeds, and EDI migrations in sequential order. |
| **`pnpm db:migrate:platform`**| Applies pending Alembic migrations to the Global Database (`postgres_global`). |
| **`pnpm db:migrate:edi`**     | Applies pending Alembic migrations to the EDI Shard Database (`edi_postgres_shard`). |
| **`pnpm db:seed`**            | Seeds default tenants, event types, and initial configuration. |
| **`pnpm db:generate`**        | Autogenerates a new Alembic migration revision based on SQLAlchemy model changes. |

---

## 🔌 Service Topology & Port Map

| Service | Port | Host URL / Connection | Description |
|---|---|---|---|
| **UCP Web Dashboard** | `5173` | [http://localhost:5173](http://localhost:5173) | Vite React Dashboard UI |
| **Unified API** | `3000` | [http://localhost:3000/docs](http://localhost:3000/docs) | FastAPI Unified HTTP Gateway & OpenAPI docs |
| **Zitadel IAM** | `8080` | [http://ucp.localhost:8080](http://ucp.localhost:8080) | Identity Provider & OAuth2/OIDC Auth Server |
| **Global PostgreSQL** | `5432` | `localhost:5432/soopa_global` | Multi-tenant control plane, users, identity, jobs |
| **EDI Shard PostgreSQL** | `5433` | `localhost:5433/edi_tenant_shard` | B2B EDI transaction shard database |
| **LocalStack** | `4566` | [http://localhost:4566](http://localhost:4566) | Local AWS mock for SQS, S3, Secrets Manager |
| **OpenAS2 Server** | `10080` | [http://localhost:10080](http://localhost:10080) | AS2 protocol inbound/outbound server and web UI |
| **SFTP Server** | `2222` | `sftp://localhost:2222` | Mock SFTP trading partner endpoint |

---

## 🧠 Development Tips

1. **Modifying Shared Packages**: If you modify code in a shared package (e.g., `core/ucp/packages/ui`), `turbo` and `tsup` will rebuild when running `pnpm dev`. If you add new exports to `package.json`, re-run `pnpm build`.
2. **Database Schema Changes**: After editing SQLAlchemy models in `core/platform/packages/database` or `apps/edi/packages/edi_database`, run `pnpm db:generate` followed by `pnpm db:migrate`.
3. **Stuck Containers or Volume Issues**: Run `pnpm infra-reset` to get a clean slate in under a minute without manual Docker commands.
