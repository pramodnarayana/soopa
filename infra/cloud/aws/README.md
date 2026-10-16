# Enterprise AWS Deployment Guide

This document outlines the standard operating procedure (SOP) for deploying the Shopify-Style Modular Monolith to AWS via Pulumi.

Because we use a heavily layered Pulumi micro-stack architecture to minimize blast radius, the stacks must be refreshed and deployed in a specific sequence to resolve cross-stack outputs correctly.

## Prerequisites
- Authenticated with AWS CLI (`aws sso login` or standard credentials)
- Active Pulumi session (`pulumi login`)
- Running commands from the repository **root directory**

---

## Phase 1: Core AWS Infrastructure Rollout (Prerequisite for Images)

To deploy manually (or for local testing), execute Pulumi commands directly from the repository root using the `-C` (working directory) and `-s <env>` (stack/environment) flags. *(Replace `<env>` with `staging` or `production`)*

```bash
# 1. Foundation (VPC, Subnets, Security Groups)
pulumi up -s <env> -C infra/cloud/aws/foundation

# 2. Data (Postgres RDS, Database Secrets)
pulumi up -s <env> -C infra/cloud/aws/data

# 3. Platform (ECS Cluster, ECR Repo, Application Load Balancers)
# IMPORTANT: This provisions the ECR Repositories required for the next phase.
pulumi up -s <env> -C infra/cloud/aws/platform
```

---

## Phase 2: Sync and Push Docker Images

Now that the Platform stack has created our AWS ECR repositories, we must populate them with our Docker images before deploying the applications.

```bash
# 1. Sync third-party images (Zitadel and OpenObserve) to your AWS ECR
./infra/cloud/aws/platform/sync-images.sh

# 2. Build and push the main Modular Monolith application image
./infra/cloud/aws/platform/build-and-push-app.sh
```

---

## Phase 3: Identity & Observability Rollout

With the images securely in our ECR, we can bring up the Identity and Observability layers.

```bash
# 4. Observability (OpenObserve)
# IMPORTANT: This stack dynamically provisions the Route53 A-Record for `obs.*`.
pulumi up -s <env> -C infra/cloud/aws/openobserve

# 5. Identity Infrastructure (Zitadel AWS Stack)
# IMPORTANT: This automatically creates the Zitadel Database Schema in RDS via `start-from-init`.
# IMPORTANT: This stack dynamically provisions the Route53 A-Record for `identity.*` so the configuration step can connect to it.
pulumi up -s <env> -C infra/cloud/aws/zitadel

# Wait for the Zitadel API to be fully healthy on ECS before proceeding.

# 6. Zitadel Identity Configuration (Zitadel Provider Stack)
# IMPORTANT: This connects to the newly created `identity.*` URL and provisions Organizations/Projects/Apps.
pulumi up -s <env> -C infra/cloud/zitadel
```

---

## Phase 4: Database Migrations & Data Seeding

Now that the core infrastructure and identity configurations are deployed, we must align the database schemas and insert the required system constants (Webhooks, Identity configs, Event Types) *before* deploying the Application code.

```bash
# From the bastion host, local machine (via VPN), or ECS run-task:

# 1. Deploy the Database Migrator Task Template
# IMPORTANT: This must be deployed first so the task definition exists in AWS!
pulumi up -s <env> -C infra/cloud/aws/apps/migrator

# 2. Run Database Migrations safely via the Typed Migrator Task Runner
uv run python -m infra_seedwork.tasks.run_ecs_migrator --env <env> --action migrate --domain all
```

---

## Phase 5: Application Rollout

Deploying the app stacks will automatically pull the monolith image you pushed in Phase 2 and spin down the old containers gracefully. Because the database was migrated in Phase 4, the new APIs and Workers will boot safely without crashing.

```bash
# 1. Deploy the Main API
pulumi up -s <env> -C infra/cloud/aws/apps/api

# 2. Deploy Background Workers
pulumi up -s <env> -C infra/cloud/aws/apps/ucp/workers
pulumi up -s <env> -C infra/cloud/aws/apps/edi/workers

# 3. Deploy EDI Transports & CDC
pulumi up -s <env> -C infra/cloud/aws/apps/edi/as2

# 4. Deploy External Tools
pulumi up -s <env> -C infra/cloud/aws/apps/openas2

# 5. Deploy Frontend Dashboard (SPA)
# IMPORTANT: Provisions the S3 Bucket and CloudFront CDN for the web application.
pulumi up -s <env> -C infra/cloud/aws/apps/dashboard

# 6. Deploy Global Edge Routing
# IMPORTANT: This stack dynamically queries the Platform ALB and Dashboard CloudFront
# outputs to automatically provision Route53 A-Records (api.*, edi.*, openas2.*, dashboard.*).
pulumi up -s <env> -C infra/cloud/aws/apps/routing
```

### CloudWatch Log Group Adoption & Migration

ECS services explicitly provision their CloudWatch Log Groups with environment-tiered retention policies (3 days for non-prod, 30 days for production) to eliminate storage leakage.

If an ECS service log group was previously created automatically by the ECS agent (`awslogs-create-group: true`), Pulumi may report a `ResourceAlreadyExistsException` on first rollout. To adopt an existing log group into Pulumi state:

```bash
# Example: Import pre-existing log group for openas2 service
pulumi import aws:cloudwatch/logGroup:LogGroup <env>-openas2-log-group /ecs/<env>-openas2 -s <env> -C infra/cloud/aws/apps/openas2

# Alternatively, pass import_log_group=True to provision_fargate_service for the initial rollout.
```

---

## Enterprise CI/CD Automation

Deployments and infrastructure provisioning are orchestrated entirely via native GitHub Actions pipelines:

1. **Cloud Infrastructure Pipelines (`check-infra.yml`, `preview-infra.yml` & `provision-infra.yml`)**:
   - Manages Foundation, Data, Platform, OpenObserve, Zitadel, OpenAS2, Dashboard Infra, and Global Routing.
   - **Static Checks (`check-infra.yml`)**: Fast, unprivileged workflow (zero AWS credentials) running linters and pure unit tests without cloud mocks on any `infra/**` PR.
   - **Speculative Cloud Diff (`preview-infra.yml`)**: OIDC-authenticated workflow generating `pulumi preview` diffs against live AWS infrastructure stacks.
   - **Cloud Infrastructure Rollout (`provision-infra.yml`)**: Event-driven rollout executing `pulumi up` on merge to `development` / `main` for platform infrastructure paths (excluding app ECS service stacks `api`, `ucp`, `edi`, and `migrator`, which roll out via App Service Rollout; `openas2`, `dashboard`, and `routing` still roll out through `provision-infra.yml`).

2. **App Continuous Delivery (`ci.yml`, `preview-app-iac.yml`, `cd-staging.yml` / `cd-prod.yml` calling `deploy.yml`)**:
   - **App CI (`ci.yml`)**: Gated on linting, unit/integration testing, and Docker image build test for pure application services (zero infra mocks).
   - **App IaC Preview (`preview-app-iac.yml`)**: Event-driven speculative diff workflow triggered when app infrastructure (`infra/cloud/aws/apps/**`) is modified, generating real Pulumi diffs against the staging cluster.
   - **App Service Rollout (`deploy.yml`)**: Triggered post-CI via `cd-staging.yml` / `cd-prod.yml`.
   - Builds and tags the single modular monolith container image (`sha-*`).
   - Runs domain-scoped database migrations via typed ECS tasks (`run_ecs_migrator`).
   - Executes rolling updates for API, UCP workers, EDI workers, and AS2 servers.
   - Builds and deploys frontend dashboard assets to S3/CloudFront (`deploy-dashboard.sh`).

3. **Monorepo Governance (`.github/CODEOWNERS`)**:
   - Infrastructure paths (`infra/**`, `.github/**`) are strictly owned by `@soopa/platform-team`.
   - Core control plane paths (`core/**`) are owned by `@soopa/domain-leads`.
   - Application domain paths (`apps/edi/**`) are owned by `@soopa/edi-team`.
