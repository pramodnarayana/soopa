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
# 4. Identity Infrastructure (Zitadel AWS Stack)
# IMPORTANT: This automatically creates the Zitadel Database Schema in RDS via `start-from-init`.
# IMPORTANT: This stack dynamically provisions the Route53 A-Record for `identity.*` so the configuration step can connect to it.
pulumi up -s <env> -C infra/cloud/aws/zitadel

# Wait for the Zitadel API to be fully healthy on ECS before proceeding.

# 5. Zitadel Identity Configuration (Zitadel Provider Stack)
# IMPORTANT: This connects to the newly created `identity.*` URL and provisions Organizations/Projects/Apps.
pulumi up -s <env> -C infra/cloud/zitadel

# 6. Observability (OpenObserve)
# IMPORTANT: This stack dynamically provisions the Route53 A-Record for `obs.*`.
pulumi up -s <env> -C infra/cloud/aws/openobserve
```

---

## Phase 4: Database Migrations & Data Seeding

Now that the core infrastructure and identity configurations are deployed, we must align the database schemas and insert the required system constants (Webhooks, Identity configs, Event Types) *before* deploying the Application code.

```bash
# From the bastion host, local machine (via VPN), or ECS run-task:

# 1. Deploy the Database Migrator Task Template
# IMPORTANT: This must be deployed first so the task definition exists in AWS!
pulumi up -s <env> -C infra/cloud/aws/apps/migrator

# 2. Run all Database Migrations AND Data Seeding safely via the Migrator Task
./infra/scripts/init_databases.sh <env>
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

---

## Enterprise CI/CD Automation

For Enterprise-grade CI/CD pipelines (like GitHub Actions), developers do not manually execute the above steps. Instead, the deployment process is highly automated to prevent human error.

You can use the deployment script which handles state synchronization (`pulumi refresh`) and deploys all infrastructure, identity configurations, and application micro-stacks automatically.

```bash
# For Staging:
./infra/scripts/ci_deploy.sh staging

# For Production:
./infra/scripts/ci_deploy.sh production
```

**Why this is Enterprise-Grade:**
- **Drift Protection**: Automatically runs `pulumi refresh` before `pulumi up`.
- **Environment Isolation**: Strictly scopes deployments via the injected `$ENV` parameter.
- **Fail-Fast**: The script executes with `set -e`, meaning any failure in the Pulumi Directed Acyclic Graph (DAG) immediately stops the pipeline to prevent partial deployments.
