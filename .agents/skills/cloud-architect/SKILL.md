---
name: cloud-architect
description: Principal AWS & Pulumi Cloud Architect profile for designing secure, cost-effective, zero-downtime AWS infrastructure, VPC/edge networking, IAM, secrets, and Expand-and-Contract rollouts.
---

# Principal AWS & Pulumi Cloud Architect Playbook

All universal monorepo laws in `.agents/AGENTS.md` apply automatically. Use this playbook when designing or reviewing AWS infrastructure in `infra/cloud/aws/`.

## AWS & Pulumi Architectural Standards

1. **Strict Two-Pipeline Expand-and-Contract Discipline**:
   - **Stateful Infra Stacks (`provision-infra.yml` / `preview-infra.yml`):** `foundation`, `data`, `platform`, `casdoor`, `openobserve`, `apps/openas2`, `apps/routing`.
   - **Stateless App Stacks (`deploy.yml` / `preview-app-iac.yml`):** `platform/migrator`, `apps/api`, `apps/edi/as2`, and worker compute stacks.
   - **Hard Rule:** Whenever a Stateful Infra stack adds a new export (`pulumi.export(...)`), ship it in a **separate Infra-Only PR** and complete `Infra Rollout` BEFORE any Stateless App stack calls `require_output(...)`. Never add preview placeholders or fallback hacks to bypass missing outputs.
2. **Pure `infra_seedwork` Primitives**:
   - Extract reusable AWS patterns (ALB/SNI certs, Route53 Alias records, S3 secure buckets, Fargate services, ECS autoscaling) into `infra/cloud/aws/packages/seedwork/infra_seedwork/`.
   - Keep `infra_seedwork` 100% domain-agnostic (zero references to `edi`, `as2`, `ucp`, `identity`, `notification`, `ip`, or brand names).
   - Return strongly-typed `@dataclass(frozen=True)` resource bundles (e.g., `SniCertificateResources`) instead of anonymous tuples.
   - Extract AWS literals (`"DNS"`, `"A"`, TTLs, limits) into `infra_seedwork.constants` frozen dataclasses and validate inputs fail-fast (e.g., RFC 1123 DNS labels, FQDN/wildcard patterns, positive TTLs, explicit `is None` checks for optional config).
3. **AWS Production Lifecycle Guardrails**:
   - **ACM Certificates + ALB SNI:** Wildcard TLS (`*.staging.flowwolf.io`) covers only one DNS label; multi-level wildcards (`*.as2.<domain>`) require a dedicated DNS-validated ACM cert attached via `aws.lb.ListenerCertificate` (SNI). Always set `opts=pulumi.ResourceOptions(delete_before_replace=False)` on `aws.acm.Certificate` paired with `allow_overwrite=True` on the Route53 validation CNAME to prevent `ResourceInUseException`.
   - **Stateful Secrets & Databases:** Protect encryption keys and DB secrets with `retain_on_delete=True` and non-zero recovery windows (7d staging, 30d production). Isolate blast radius with dedicated secrets per concern.
   - **Zero-Trust Private Networking:** Run all application compute, RDS databases, and internal gateways in private subnets with least-privilege Security Group rules (explicit port + source SG, never `0.0.0.0/0` ingress on app/DB SGs).
   - **Least-Privilege IAM:** Scope `secretsmanager:GetSecretValue`, `s3:*`, and `kms:*` strictly to exact resource ARNs; separate execution roles vs. task roles.
   - **IPv4 vs. Dualstack Parity:** Only provision Route53 `AAAA` Alias records if the target ALB is explicitly `dualstack`; IPv4 ALBs use `A` Alias records only.

## Execution & Review Workflow

1. **Topology Diagram:** Include a Mermaid architecture diagram showing public edge (Route53/ACM/ALB) → private VPC boundary → ECS/RDS/S3/Secrets Manager.
2. **Cost-Benefit Justification:** Provide a crisp Cost-Benefit table justifying every AWS managed service choice (operational overhead + monthly cost delta, e.g., ALB SNI \$0 vs. new ALB \$22+/mo, Route53 Alias \$0/query, ACM public cert \$0).
3. **Pulumi Runtime Contract Tests:** Verify every new `infra_seedwork` primitive and stack change with Pulumi Runtime Mocks (`pulumi.runtime.Mocks`) and static stack contract assertions in `infra/cloud/aws/tests/`.
4. **Verification Gates:** Run `.venv/bin/pytest infra/cloud/aws/tests infra/cloud/aws/packages/seedwork/tests`, `.venv/bin/ruff check infra/cloud`, and `MYPYPATH=infra/cloud/aws/packages/seedwork .venv/bin/mypy --follow-imports=silent <modified_files>`.
