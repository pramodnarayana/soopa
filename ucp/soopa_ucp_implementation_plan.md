# Enterprise Architecture Plan: Soopa Unified Platform

This document serves as the master architectural blueprint for the Soopa unified control plane. It outlines the strategy for standardizing Identity, Scheduling, Notifications, Observability, and other core capabilities across a polyglot microservice environment (TypeScript/Node.js, Python, Rust).

---

## 1. Core Architectural Philosophy

To support multiple business applications (EDI processing, Integration platform, Document processing) without duplicating complex business logic, we must adopt a **Hybrid Monorepo Architecture**. 

We strictly divide platform capabilities into two categories:

### A. Stateless Capabilities (In-Process SDKs)
- **Examples:** Identity (JWT validation, RBAC), Observability (OpenTelemetry traces), Feature Flags.
- **How it works:** The engine runs *inside* the business application's memory. When an app calls `identity.validateToken()`, the cryptographic validation happens locally. 
- **Why:** These operations must happen on every single HTTP request. Making a network call to a central microservice for every request would introduce catastrophic latency and a massive single point of failure.

### B. Stateful Capabilities (Centralized Microservice + API Clients)
- **Examples:** Scheduler (Cron polling, DB locks), Notifications (Template rendering, email/slack routing, retries), Metering/Billing, Audit Logging.
- **How it works:** The complex engine (background polling, transactional outbox sweeping) runs entirely in a centralized **Platform Server**. The business applications import a lightweight SDK, but this SDK is simply a "thin API client" (a dumb phone). When a Node app calls `platform.scheduleJob()`, the SDK just makes an HTTP/gRPC call to the central platform server.
- **Why:** If multiple apps (Node, Python, Rust) attempted to poll the same database to run scheduled jobs simultaneously, it would cause severe race conditions and split-brains. Centralizing the stateful engines guarantees transactional integrity.

---

## 2. Monorepo Directory Structure (`soopaplatform`)

By unifying all of these modules into a single monorepo, we eliminate dependency hell across multiple repositories. A developer can clone one repo to see the entire platform specification, servers, and SDKs.

```text
soopaplatform/
├── server/                       # The Stateful Central Engines
│   ├── scheduler_engine/         # Evaluates cron rules, manages DB locks, fires webhooks
│   ├── notification_engine/      # Renders templates, routes outbox events to SES/Slack
│   ├── ucp-api/                  # (New) Management API for Tenants and API Keys
│   ├── metering_engine/          # Aggregates usage data for billing quotas (Stripe)
│   └── audit_engine/             # High-throughput sink for compliance activity logs
│
├── apps/                         # Platform User Interfaces
│   └── developer-portal/         # React/Next.js UI for tenants to manage keys, webhooks, and logs
│
├── packages/                     # Internal Shared Modules (Turborepo)
│   ├── database/                 # Drizzle ORM schemas shared across all Node servers
│   └── identity/                 # Stateless Identity SDKs (Python, Node) for JWT/RBAC checks
│
├── sdks/                         # Polyglot Libraries (Consumed by External Business Apps)
│   ├── node/                     # Published to internal npm
│   │   ├── @soopa/observability  # Standardized OTel wrappers
│   │   ├── @soopa/scheduler      # API Client to talk to `server/scheduler_engine`
│   │   └── @soopa/notification   # API Client to talk to `server/notification_engine`
│   │
│   ├── python/                   # Published to internal PyPI
│   │   ├── soopa-scheduler       # HTTP client for Python apps
│   │   └── ...
│   │
│   └── rust/                     # Published to internal Cargo registry
│       └── ...
│
├── specification/                # Language-Agnostic Contracts
│   ├── openapi/                  # REST API schemas defining how SDKs talk to the `server/`
│   └── grpc/                     # Protobufs (if gRPC is used for low-latency engine comms)
│
└── infrastructure/               # Platform DevOps (IaC)
    └── docker-compose.yml        # Local dev stack (Zitadel, Postgres, Platform Server, Redis)
```

---

## 3. Language Strategy

To adhere to the requirement of **keeping the number of languages to a minimum**:

1. **The Server Engines (`server/`):** 
   - We will write the centralized platform engines in **TypeScript/Node.js** or **Python**. 
   - *Recommendation:* Because Node.js is phenomenal at high-concurrency async I/O (perfect for firing thousands of webhooks and dispatching emails concurrently), and because the team already uses it for the integration platform, **TypeScript/Node.js is highly recommended** for the central platform server.
   - We specifically avoid introducing Go (Golang) to keep the organizational language count strictly minimized.
2. **The SDKs (`sdks/`):**
   - Must be written in TypeScript, Python, and Rust natively to match the business applications consuming them.

---

## 4. Deep Dive: The Custom Lightweight Notification System

Instead of deploying a heavy open-source tool like Novu (which requires maintaining MongoDB and Redis clusters), we will build a **Custom Lightweight Notification System** mirroring our successful scheduler architecture.

### Cost & Effort Analysis
- **Infrastructure Cost:** $0. It runs on our existing Postgres database and Node/Python compute. No external Mongo/Redis required.
- **Maintenance Burden:** Extremely low.
- **Enterprise Flexibility:** 100% control over multi-tenant data privacy and routing.

### Architecture Details
1. **Templates in Postgres:** The control plane database stores the notification templates per channel (Email, Slack, SMS). We will use a lightweight rendering engine (like Jinja2 or Handlebars) to merge data payloads into the templates.
2. **The Outbox Pattern (Store-and-Forward):** 
   - A business app (e.g., Python EDI) encounters an error. It saves an `OutboxEvent` (triggering an alert) to its local DB in the exact same transaction.
   - A local sweeper picks up the outbox event and uses the `soopa-notification` SDK to POST to the central `notification_engine`.
   - The central engine stores the event as `PENDING`, renders the template, and dispatches it via AWS SES or Slack.
   - If AWS SES is down, the central engine retries automatically. The business app remains completely unaware and unharmed.

---

## 5. Developer Portal UI

The unified architecture enables a single **Developer Portal** (`apps/developer-portal`). Because the identity, scheduler, notifications, and metering all live in one monorepo, they share the same control plane database.

The Portal will feature:
- **Keys & Auth:** Managing Zitadel API keys securely.
- **Webhooks (Scheduler):** Where tenants view registered chron jobs and target webhook URLs.
- **Inbox/Logs:** A central view for tracing failed notifications and audit logs.
- **Feature Flags:** Toggling modules per tenant without redeploying code.

---

## Approval Check

> [!IMPORTANT]
> This master document captures all context discussed regarding stateless vs stateful logic, monorepo structures, and the custom notification/scheduler build. 
> 
> Please review. If this comprehensive blueprint is approved, we can close this discussion and begin scoping the initialization of the `soopaplatform` repository.
