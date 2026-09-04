"""
EDI Compute Infrastructure
===========================

Provisions the full compute layer for the EDI platform using the Shopify-style
single-image / multiple-container deployment strategy:

  - One ECR repository holds the single production Docker image.
  - One ECS Fargate cluster runs N services, each using the same image but
    overriding the CMD to boot a different worker.
  - Every ECS task pairs the main app container with the ``edi-secrets-sidecar``
    container, which syncs AWS Secrets Manager secrets (AS2 private keys,
    certificates) to a shared ``/mnt/secrets`` in-memory tmpfs volume every 5 min.
  - An Application Load Balancer (ALB) fronts only the ``edi-as2-server`` service.
  - All other workers are purely internal SQS consumers with no public ingress.

Shopify-style entrypoint override mapping
-----------------------------------------
Same ECR image → different CMD per service:

  edi-as2-server          → uvicorn as2_server.main:app --host 0.0.0.0 --port 8000
  edi-background-worker   → python -m edi_background_worker.main
  edi-compute-worker      → python -m compute_worker.main
  edi-orchestrator-worker → python -m worker.main
  edi-config-sync-worker  → python -m config_sync_worker.provision.main

IAM design (Least Privilege — no wildcards)
-------------------------------------------
Region and account ID are resolved at deploy time via ``aws.get_region()`` and
``aws.get_caller_identity()`` so ARNs are always fully qualified.

  Shared (all services via edi-secrets-sidecar):
    secretsmanager:ListSecrets  → Resource: "*"  (AWS does not support scoping)
    secretsmanager:GetSecretValue → arn:aws:secretsmanager:<region>:<account>:secret:edi/*

  edi-as2-server:
    s3:PutObject + GetObject  on edi-payloads bucket
    sns:Publish               on edi-events SNS topic
    sqs:SendMessage           on all EDI SQS queues

  edi-background-worker:
    sqs:ReceiveMessage + DeleteMessage + ChangeMessageVisibility + GetQueueAttributes
      on edi-control-plane-jobs + edi-data-plane-jobs queues and their DLQs
    sns:Publish on edi-events topic

  edi-compute-worker:
    sqs:ReceiveMessage + DeleteMessage + ChangeMessageVisibility + GetQueueAttributes
      on edi-transform queue and its DLQ
    s3:GetObject + PutObject on edi-payloads bucket

  edi-orchestrator-worker:
    sqs:ReceiveMessage + DeleteMessage + ChangeMessageVisibility + GetQueueAttributes
      on edi-lifecycle queue and its DLQ

  edi-config-sync-worker:
    sqs:ReceiveMessage + DeleteMessage + ChangeMessageVisibility + GetQueueAttributes
      on edi-config-sync queue and its DLQ

Networking
----------
A dedicated VPC is provisioned with:
  - 2 public subnets  → ALB (internet-facing)
  - 2 private subnets → all ECS Fargate tasks (NAT Gateway for outbound egress)
"""

import json
from dataclasses import dataclass

import pulumi
import pulumi_aws as aws

from edi.messaging import EdiMessagingStack
from edi.storage import EdiStorageStack

# ── Constants ──────────────────────────────────────────────────────────────────

_TAGS: dict[str, str] = {"ManagedBy": "pulumi", "Component": "edi"}
_SECRETS_MOUNT_PATH = "/mnt/secrets"
_SECRETS_PREFIX = "edi/"
_LOG_GROUP = "/ecs/edi-platform"
_ECR_REPO_NAME = "edi-platform"

# Sidecar entrypoint: absolute path avoids workingDirectory / sys.path ambiguity.
_SIDECAR_CMD = ["python", "/app/apps/edi/apps/edi-secrets-sidecar/main.py"]

# ── Resolved AWS identity (module-level — evaluated once per Pulumi run) ──────
#
# These are used to build fully-qualified, region+account-scoped IAM resource
# ARNs. Using "*:*" wildcards in ARNs is a security violation that expands
# permissions to all regions and all accounts. All policy ARNs in this module
# are constructed from these resolved values.

_region: aws.GetRegionResult = aws.get_region()
_identity: aws.GetCallerIdentityResult = aws.get_caller_identity()

# Fully-qualified Secrets Manager ARN prefix — scoped to this region + account.
# Used by GetSecretValue. ListSecrets MUST use Resource: "*" per AWS enforcement.
_SCOPED_SECRET_ARN_PREFIX = (
    f"arn:aws:secretsmanager:{_region.name}:{_identity.account_id}:secret:{_SECRETS_PREFIX}*"
)


# ── Helper dataclasses ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Networking:
    """All VPC-level resources used by the compute stack."""

    vpc: aws.ec2.Vpc
    public_subnets: list[aws.ec2.Subnet]
    private_subnets: list[aws.ec2.Subnet]
    alb_sg: aws.ec2.SecurityGroup
    app_sg: aws.ec2.SecurityGroup


@dataclass(frozen=True)
class _ServiceSpec:
    """
    Declarative spec for a single ECS Fargate service.

    Passed to ``_provision_service()`` so that the provisioning logic is expressed
    once and the per-service differences are data, not duplicated code.
    """

    logical_name: str
    command: list[str]
    cpu: str
    memory: str
    desired_count: int
    task_role: aws.iam.Role
    port: int | None = None


@dataclass(frozen=True)
class _ServiceResources:
    """
    Resources produced by ``_provision_service()`` for one ECS service.

    The ``service`` reference is used by callers that need to register
    load-balancer attachments (e.g. the AS2 server).
    """

    task_definition: aws.ecs.TaskDefinition
    service: aws.ecs.Service


# ── VPC Provisioning ───────────────────────────────────────────────────────────


def _provision_networking() -> _Networking:
    """
    Provisions a dedicated VPC for the EDI platform.

    Layout:
      10.0.0.0/16  — VPC CIDR
        10.0.0.0/24  — public-a  (us-east-1a)  → ALB
        10.0.1.0/24  — public-b  (us-east-1b)  → ALB
        10.0.10.0/24 — private-a (us-east-1a)  → ECS Fargate tasks
        10.0.11.0/24 — private-b (us-east-1b)  → ECS Fargate tasks

    A single NAT Gateway in public-a provides outbound internet egress for the
    private subnets (SQS, SNS, ECR, Secrets Manager API calls).

    Security groups:
      alb_sg — ingress: 443 + 80 from 0.0.0.0/0
               egress:  port 8000 to the VPC CIDR (target containers)
      app_sg — ingress: port 8000 from alb_sg only
               egress:  all (required for SQS/SNS/ECR/SecretsManager via NAT)
    """
    vpc = aws.ec2.Vpc(
        "edi-vpc",
        cidr_block="10.0.0.0/16",
        enable_dns_hostnames=True,
        enable_dns_support=True,
        tags={**_TAGS, "Name": "edi-platform-vpc"},
    )

    igw = aws.ec2.InternetGateway(
        "edi-igw",
        vpc_id=vpc.id,
        tags={**_TAGS, "Name": "edi-platform-igw"},
    )

    # ── Public subnets (ALB lives here) ────────────────────────────────────
    public_subnet_a = aws.ec2.Subnet(
        "edi-public-subnet-a",
        vpc_id=vpc.id,
        cidr_block="10.0.0.0/24",
        availability_zone=f"{_region.name}a",
        map_public_ip_on_launch=True,
        tags={**_TAGS, "Name": "edi-public-a"},
    )
    public_subnet_b = aws.ec2.Subnet(
        "edi-public-subnet-b",
        vpc_id=vpc.id,
        cidr_block="10.0.1.0/24",
        availability_zone=f"{_region.name}b",
        map_public_ip_on_launch=True,
        tags={**_TAGS, "Name": "edi-public-b"},
    )

    public_rt = aws.ec2.RouteTable(
        "edi-public-rt",
        vpc_id=vpc.id,
        routes=[aws.ec2.RouteTableRouteArgs(cidr_block="0.0.0.0/0", gateway_id=igw.id)],
        tags={**_TAGS, "Name": "edi-public-rt"},
    )
    aws.ec2.RouteTableAssociation(
        "edi-public-rta-a", subnet_id=public_subnet_a.id, route_table_id=public_rt.id
    )
    aws.ec2.RouteTableAssociation(
        "edi-public-rta-b", subnet_id=public_subnet_b.id, route_table_id=public_rt.id
    )

    # ── NAT Gateway (single, in public-a) for private subnet egress ────────
    eip = aws.ec2.Eip("edi-nat-eip", domain="vpc", tags={**_TAGS, "Name": "edi-nat-eip"})
    nat_gw = aws.ec2.NatGateway(
        "edi-nat-gw",
        subnet_id=public_subnet_a.id,
        allocation_id=eip.id,
        tags={**_TAGS, "Name": "edi-nat-gw"},
    )

    # ── Private subnets (ECS Fargate tasks live here) ───────────────────────
    private_subnet_a = aws.ec2.Subnet(
        "edi-private-subnet-a",
        vpc_id=vpc.id,
        cidr_block="10.0.10.0/24",
        availability_zone=f"{_region.name}a",
        tags={**_TAGS, "Name": "edi-private-a"},
    )
    private_subnet_b = aws.ec2.Subnet(
        "edi-private-subnet-b",
        vpc_id=vpc.id,
        cidr_block="10.0.11.0/24",
        availability_zone=f"{_region.name}b",
        tags={**_TAGS, "Name": "edi-private-b"},
    )

    private_rt = aws.ec2.RouteTable(
        "edi-private-rt",
        vpc_id=vpc.id,
        routes=[aws.ec2.RouteTableRouteArgs(cidr_block="0.0.0.0/0", nat_gateway_id=nat_gw.id)],
        tags={**_TAGS, "Name": "edi-private-rt"},
    )
    aws.ec2.RouteTableAssociation(
        "edi-private-rta-a", subnet_id=private_subnet_a.id, route_table_id=private_rt.id
    )
    aws.ec2.RouteTableAssociation(
        "edi-private-rta-b", subnet_id=private_subnet_b.id, route_table_id=private_rt.id
    )

    # ── Security Groups ──────────────────────────────────────────────────────
    alb_sg = aws.ec2.SecurityGroup(
        "edi-alb-sg",
        vpc_id=vpc.id,
        description="ALB: accepts HTTPS + HTTP-redirect from internet, forwards to app containers",
        ingress=[
            aws.ec2.SecurityGroupIngressArgs(
                description="HTTPS from internet",
                from_port=443,
                to_port=443,
                protocol="tcp",
                cidr_blocks=["0.0.0.0/0"],
            ),
            aws.ec2.SecurityGroupIngressArgs(
                description="HTTP (redirect to HTTPS)",
                from_port=80,
                to_port=80,
                protocol="tcp",
                cidr_blocks=["0.0.0.0/0"],
            ),
        ],
        egress=[
            aws.ec2.SecurityGroupEgressArgs(
                description="Forward to ECS containers on app port 8000",
                from_port=8000,
                to_port=8000,
                protocol="tcp",
                cidr_blocks=["10.0.0.0/16"],
            )
        ],
        tags={**_TAGS, "Name": "edi-alb-sg"},
    )

    app_sg = aws.ec2.SecurityGroup(
        "edi-app-sg",
        vpc_id=vpc.id,
        description="ECS tasks: accept from ALB only, allow all egress via NAT",
        ingress=[
            aws.ec2.SecurityGroupIngressArgs(
                description="Traffic from ALB only",
                from_port=8000,
                to_port=8000,
                protocol="tcp",
                source_security_group_id=alb_sg.id,
            )
        ],
        egress=[
            aws.ec2.SecurityGroupEgressArgs(
                description="All outbound — SQS/SNS/ECR/SecretsManager via NAT Gateway",
                from_port=0,
                to_port=0,
                protocol="-1",
                cidr_blocks=["0.0.0.0/0"],
            )
        ],
        tags={**_TAGS, "Name": "edi-app-sg"},
    )

    return _Networking(
        vpc=vpc,
        public_subnets=[public_subnet_a, public_subnet_b],
        private_subnets=[private_subnet_a, private_subnet_b],
        alb_sg=alb_sg,
        app_sg=app_sg,
    )


# ── ECR ────────────────────────────────────────────────────────────────────────


def _provision_ecr() -> aws.ecr.Repository:
    """
    Provisions the single ECR repository that stores the monolith image.

    Lifecycle policy:
      Priority 1 — Purge untagged images after 1 day (prevents registry bloat
                   from CI build layers that were never tagged for release).
      Priority 2 — Keep the last 30 images tagged with ``sha-`` or ``v`` prefix.
                   Older releases are expired automatically.
    """
    repo = aws.ecr.Repository(
        _ECR_REPO_NAME,
        name=_ECR_REPO_NAME,
        image_scanning_configuration=aws.ecr.RepositoryImageScanningConfigurationArgs(
            scan_on_push=True,
        ),
        image_tag_mutability="MUTABLE",
        tags=_TAGS,
    )

    aws.ecr.LifecyclePolicy(
        f"{_ECR_REPO_NAME}-lifecycle",
        repository=repo.name,
        policy=json.dumps(
            {
                "rules": [
                    {
                        "rulePriority": 1,
                        "description": "Purge untagged images after 1 day",
                        "selection": {
                            "tagStatus": "untagged",
                            "countType": "sinceImagePushed",
                            "countUnit": "days",
                            "countNumber": 1,
                        },
                        "action": {"type": "expire"},
                    },
                    {
                        "rulePriority": 2,
                        "description": "Keep last 30 tagged release images",
                        "selection": {
                            "tagStatus": "tagged",
                            "tagPrefixList": ["sha-", "v"],
                            "countType": "imageCountMoreThan",
                            "countNumber": 30,
                        },
                        "action": {"type": "expire"},
                    },
                ]
            }
        ),
    )

    return repo


# ── Shared ECS Task Execution Role ─────────────────────────────────────────────


def _make_execution_role() -> aws.iam.Role:
    """
    A single ECS task execution role shared by all services.

    This role is assumed by the ECS control plane (not application code) to:
      - Pull the container image from ECR.
      - Write task stdout/stderr logs to CloudWatch Logs.
      - Resolve ``secrets:`` references from Secrets Manager into env vars
        at task launch time (used for injecting non-PEM secrets such as DB URL).

    The ``secretsmanager:GetSecretValue`` grant here is for the ECS agent's
    task-launch-time injection. The sidecar's runtime Secrets Manager access
    is granted separately on each service's Task Role.

    All ARNs are fully qualified using the resolved region and account ID —
    no ``*:*`` wildcards.
    """
    role = aws.iam.Role(
        "edi-ecs-execution-role",
        assume_role_policy=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
        tags=_TAGS,
    )

    # AWS-managed policy covers: ECR pull + CloudWatch Logs
    aws.iam.RolePolicyAttachment(
        "edi-ecs-execution-role-managed-policy",
        role=role.name,
        policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    )

    # Scoped GetSecretValue for ECS task-launch-time secrets injection.
    # ARN is fully qualified — region + account resolved at deploy time.
    aws.iam.RolePolicy(
        "edi-ecs-execution-role-secrets",
        role=role.id,
        policy=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AllowECSAgentSecretInjection",
                        "Effect": "Allow",
                        "Action": ["secretsmanager:GetSecretValue"],
                        "Resource": _SCOPED_SECRET_ARN_PREFIX,
                    }
                ],
            }
        ),
    )

    return role


# ── Per-Service Task Role Builder ──────────────────────────────────────────────


def _make_task_role(
    logical_name: str,
    extra_statements: pulumi.Output[list[dict[str, object]]],
) -> aws.iam.Role:
    """
    Provisions a least-privilege IAM Task Role for one ECS service.

    Every task role includes two shared sidecar statements:
      1. ``secretsmanager:ListSecrets`` on ``Resource: "*"``
         AWS does NOT support resource-level restrictions for list-level actions.
         Using a scoped ARN here is silently ignored by IAM and would give a false
         sense of security. The correct approach is to acknowledge the AWS limitation
         and keep it explicit in a dedicated statement with a descriptive SID.
      2. ``secretsmanager:GetSecretValue`` on the fully-qualified ``edi/*`` ARN prefix
         (region + account resolved via ``aws.get_region()`` / ``aws.get_caller_identity()``).

    Per-service permissions are passed as ``extra_statements``, which is a
    ``pulumi.Output[list[dict]]`` because the resource ARNs it references are
    themselves Pulumi Outputs that must be resolved asynchronously. The entire
    policy JSON document is therefore constructed inside ``.apply()`` so Pulumi
    can fully resolve all Output dependencies before serialising.
    """
    role = aws.iam.Role(
        f"edi-{logical_name}-task-role",
        assume_role_policy=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
        tags={**_TAGS, "Name": f"edi-{logical_name}-task-role"},
    )

    # Shared sidecar statements — baked in for every service.
    # These are plain dicts (not Outputs), so they can be merged inside .apply().
    _sidecar_list_statement: dict[str, object] = {
        "Sid": "SidecarListSecrets",
        "Effect": "Allow",
        "Action": ["secretsmanager:ListSecrets"],
        # AWS list-level action: resource scoping is not supported.
        # Documented: https://docs.aws.amazon.com/secretsmanager/latest/userguide/reference_iam-permissions.html
        "Resource": "*",
    }
    _sidecar_get_statement: dict[str, object] = {
        "Sid": "SidecarGetSecretValue",
        "Effect": "Allow",
        "Action": ["secretsmanager:GetSecretValue"],
        # Fully-qualified ARN — no *:* wildcards.
        "Resource": _SCOPED_SECRET_ARN_PREFIX,
    }

    # The entire policy document is assembled inside .apply() so that Pulumi
    # resolves all Output-valued ARNs in extra_statements before json.dumps().
    policy_doc: pulumi.Output[str] = extra_statements.apply(
        lambda stmts: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    _sidecar_list_statement,
                    _sidecar_get_statement,
                    *stmts,
                ],
            }
        )
    )

    aws.iam.RolePolicy(
        f"edi-{logical_name}-task-policy",
        role=role.id,
        policy=policy_doc,
    )

    return role


# ── Task Definition Builder ────────────────────────────────────────────────────


def _make_task_definition(
    logical_name: str,
    image_uri: pulumi.Output[str],
    command: list[str],
    task_role: aws.iam.Role,
    execution_role: aws.iam.Role,
    log_group: aws.cloudwatch.LogGroup,
    cpu: str = "512",
    memory: str = "1024",
    port: int | None = None,
    environment: list[dict[str, str]] | None = None,
) -> aws.ecs.TaskDefinition:
    """
    Builds an ECS Fargate task definition with two containers:

    1. **edi-secrets-sidecar** — persistent background process that polls AWS Secrets
       Manager every 5 minutes, writing AS2 private keys and certificates as ``.pem``
       files to the shared ``/mnt/secrets`` in-memory tmpfs volume. It is marked
       ``essential: true`` so that if it crashes, ECS will replace the entire task.
       Entrypoint is the absolute path to ``main.py`` to avoid ``sys.path`` issues.

    2. **app** (``logical_name``) — the main worker container. Reads ``.pem`` files
       from ``/mnt/secrets`` (read-only mount). Declares ``dependsOn: [sidecar: START]``
       so it does not start until the sidecar is running (ensuring secrets are available
       on disk before the app process begins).

    The ``/mnt/secrets`` volume is a Fargate bind-mount (no host path specified),
    which is equivalent to a tmpfs — secrets are never written to persistent disk.

    The ``awslogs-region`` is resolved from ``_region.name`` (module-level, deploy-time)
    rather than being hardcoded, so the same Pulumi program works in any AWS region.
    """
    env: list[dict[str, str]] = environment or []

    port_mappings: list[dict[str, object]] = []
    if port is not None:
        port_mappings = [{"containerPort": port, "hostPort": port, "protocol": "tcp"}]

    # All values inside this .apply() are fully resolved Pulumi Outputs.
    # _region.name is a plain str (synchronous result of get_region()).
    container_definitions: pulumi.Output[str] = pulumi.Output.all(image_uri, log_group.name).apply(
        lambda args: json.dumps(
            [
                # ── Container 1: edi-secrets-sidecar ──────────────────────
                {
                    "name": "edi-secrets-sidecar",
                    "image": args[0],
                    # Absolute path avoids workingDirectory + sys.path ambiguity.
                    # `python -m main` with a custom workingDirectory requires main.py
                    # to be importable as a module, which it is not (no __init__.py).
                    "command": _SIDECAR_CMD,
                    "essential": True,
                    "environment": [
                        {"name": "SECRETS_MOUNT_PATH", "value": _SECRETS_MOUNT_PATH},
                    ],
                    "mountPoints": [
                        {
                            "sourceVolume": "secrets",
                            "containerPath": _SECRETS_MOUNT_PATH,
                            "readOnly": False,
                        }
                    ],
                    "logConfiguration": {
                        "logDriver": "awslogs",
                        "options": {
                            "awslogs-group": args[1],
                            # Region resolved at deploy time — not hardcoded.
                            "awslogs-region": _region.name,
                            "awslogs-stream-prefix": f"{logical_name}/sidecar",
                        },
                    },
                },
                # ── Container 2: main application ──────────────────────────
                {
                    "name": logical_name,
                    "image": args[0],
                    "command": command,
                    "essential": True,
                    "portMappings": port_mappings,
                    "environment": env,
                    "mountPoints": [
                        {
                            "sourceVolume": "secrets",
                            "containerPath": _SECRETS_MOUNT_PATH,
                            # App reads secrets — write access belongs to the sidecar only.
                            "readOnly": True,
                        }
                    ],
                    "dependsOn": [
                        {
                            "containerName": "edi-secrets-sidecar",
                            # START condition: app starts once the sidecar process is
                            # running. The sidecar's first sync completes in seconds.
                            "condition": "START",
                        }
                    ],
                    "logConfiguration": {
                        "logDriver": "awslogs",
                        "options": {
                            "awslogs-group": args[1],
                            "awslogs-region": _region.name,
                            "awslogs-stream-prefix": f"{logical_name}/app",
                        },
                    },
                },
            ]
        )
    )

    return aws.ecs.TaskDefinition(
        f"edi-{logical_name}-task",
        family=f"edi-{logical_name}",
        cpu=cpu,
        memory=memory,
        network_mode="awsvpc",
        requires_compatibilities=["FARGATE"],
        execution_role_arn=execution_role.arn,
        task_role_arn=task_role.arn,
        container_definitions=container_definitions,
        # Fargate bind-mount with no host path = ephemeral in-memory volume.
        # Secrets never touch persistent disk.
        volumes=[aws.ecs.TaskDefinitionVolumeArgs(name="secrets")],
        tags=_TAGS,
    )


# ── ECS Service Factory ────────────────────────────────────────────────────────


def _provision_service(
    spec: _ServiceSpec,
    cluster: aws.ecs.Cluster,
    execution_role: aws.iam.Role,
    image_uri: pulumi.Output[str],
    log_group: aws.cloudwatch.LogGroup,
    net: _Networking,
    load_balancers: list[aws.ecs.ServiceLoadBalancerArgs] | None = None,
) -> _ServiceResources:
    """
    Provisions a task definition + ECS Fargate service from a ``_ServiceSpec``.

    Centralising the provisioning logic here ensures all services share the same
    deployment defaults (circuit breaker with rollback, no public IP, private
    subnets only) without duplicating them per-service.

    ``load_balancers`` is only passed for ``edi-as2-server`` — all other services
    are internal SQS consumers with no ALB attachment.
    """
    task_def = _make_task_definition(
        logical_name=spec.logical_name,
        image_uri=image_uri,
        command=spec.command,
        task_role=spec.task_role,
        execution_role=execution_role,
        log_group=log_group,
        cpu=spec.cpu,
        memory=spec.memory,
        port=spec.port,
    )

    service = aws.ecs.Service(
        f"edi-{spec.logical_name}-svc",
        cluster=cluster.arn,
        task_definition=task_def.arn,
        desired_count=spec.desired_count,
        launch_type="FARGATE",
        network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
            subnets=[s.id for s in net.private_subnets],
            security_groups=[net.app_sg.id],
            assign_public_ip=False,
        ),
        load_balancers=load_balancers or [],
        deployment_circuit_breaker=aws.ecs.ServiceDeploymentCircuitBreakerArgs(
            enable=True,
            rollback=True,
        ),
        tags=_TAGS,
    )

    return _ServiceResources(task_definition=task_def, service=service)


# ── ALB (AS2 Server only) ──────────────────────────────────────────────────────


def _provision_alb(
    net: _Networking,
) -> tuple[aws.lb.LoadBalancer, aws.lb.TargetGroup]:
    """
    Provisions an internet-facing ALB for the AS2 HTTP server.

    HTTP  :80  → 301 redirect to HTTPS.
    HTTPS :443 → forward to edi-as2-server target group on port 8000.

    TLS policy ``ELBSecurityPolicy-TLS13-1-2-2021-06`` enforces TLS 1.2+ with
    TLS 1.3 preferred — satisfies AS2 security requirements.

    ``acm_certificate_arn`` is required from stack config. ``config.require()``
    causes an intentional deploy-time failure if the cert ARN is missing,
    preventing insecure deployments with no TLS termination.
    """
    config = pulumi.Config("edi-platform")
    acm_cert_arn = config.require("acm_certificate_arn")

    alb = aws.lb.LoadBalancer(
        "edi-as2-alb",
        internal=False,
        load_balancer_type="application",
        security_groups=[net.alb_sg.id],
        subnets=[s.id for s in net.public_subnets],
        enable_deletion_protection=True,
        tags={**_TAGS, "Name": "edi-as2-alb"},
    )

    tg = aws.lb.TargetGroup(
        "edi-as2-tg",
        port=8000,
        protocol="HTTP",
        target_type="ip",
        vpc_id=net.vpc.id,
        health_check=aws.lb.TargetGroupHealthCheckArgs(
            path="/health",
            port="8000",
            protocol="HTTP",
            healthy_threshold=2,
            unhealthy_threshold=3,
            interval=30,
            timeout=10,
            matcher="200",
        ),
        tags=_TAGS,
    )

    # HTTP → HTTPS 301 redirect
    aws.lb.Listener(
        "edi-as2-alb-http-redirect",
        load_balancer_arn=alb.arn,
        port=80,
        protocol="HTTP",
        default_actions=[
            aws.lb.ListenerDefaultActionArgs(
                type="redirect",
                redirect=aws.lb.ListenerDefaultActionRedirectArgs(
                    port="443",
                    protocol="HTTPS",
                    status_code="HTTP_301",
                ),
            )
        ],
    )

    # HTTPS listener — TLS 1.3 preferred, TLS 1.2 minimum
    aws.lb.Listener(
        "edi-as2-alb-https",
        load_balancer_arn=alb.arn,
        port=443,
        protocol="HTTPS",
        ssl_policy="ELBSecurityPolicy-TLS13-1-2-2021-06",
        certificate_arn=acm_cert_arn,
        default_actions=[
            aws.lb.ListenerDefaultActionArgs(
                type="forward",
                target_group_arn=tg.arn,
            )
        ],
    )

    return alb, tg


# ── Main Compute Stack ─────────────────────────────────────────────────────────


class EdiComputeStack:
    """
    Composes the full compute layer for the EDI platform.

    Orchestrates five ECS Fargate services, each driven from the same ECR image
    with per-service CMD overrides (Shopify-style). Every service runs the
    ``edi-secrets-sidecar`` as a persistent companion container.

    Instantiate once from ``__main__.py``. Messaging and storage stacks are
    injected so resource ARNs are resolved at Pulumi graph-build time — no
    dynamic AWS API calls (e.g. ``boto3.get_queue_url``) at runtime.

    Public attributes (consumed by ``__main__.py`` for export):
      ecr_repository_url  — CI pushes the built image here
      cluster_name        — CI/CD deploy commands target this cluster
      alb_dns_name        — Point your AS2 DNS CNAME to this address
    """

    def __init__(
        self,
        messaging: EdiMessagingStack,
        storage: EdiStorageStack,
    ) -> None:
        config = pulumi.Config("edi-platform")
        image_tag: str = config.require("image_tag")

        # ── Core shared infrastructure ─────────────────────────────────────
        net = _provision_networking()
        ecr = _provision_ecr()
        self.ecr_repository_url: pulumi.Output[str] = ecr.repository_url

        cluster = aws.ecs.Cluster(
            "edi-platform-cluster",
            name="edi-platform",
            settings=[aws.ecs.ClusterSettingArgs(name="containerInsights", value="enabled")],
            tags=_TAGS,
        )
        self.cluster_name: pulumi.Output[str] = cluster.name

        log_group = aws.cloudwatch.LogGroup(
            "edi-logs",
            name=_LOG_GROUP,
            retention_in_days=config.require_int("log_retention_days"),
            tags=_TAGS,
        )
        execution_role = _make_execution_role()

        # Full image URI: <ecr_repo_url>:<image_tag>
        # image_tag is a plain str from Pulumi config, so .apply() is sufficient.
        image_uri: pulumi.Output[str] = ecr.repository_url.apply(lambda url: f"{url}:{image_tag}")

        # ── ALB for AS2 server ─────────────────────────────────────────────
        alb, as2_tg = _provision_alb(net)
        self.alb_dns_name: pulumi.Output[str] = alb.dns_name

        # ── edi-as2-server ─────────────────────────────────────────────────
        # Internet-facing HTTP service. Needs:
        #   - s3: read/write payloads
        #   - sns: publish inbound events
        #   - sqs: enqueue work to all downstream queues
        as2_extra: pulumi.Output[list[dict[str, object]]] = pulumi.Output.all(
            storage.edi_payloads.arn,
            messaging.edi_events_topic.arn,
            messaging.edi_transform.queue.arn,
            messaging.edi_deliver.queue.arn,
            messaging.edi_lifecycle.queue.arn,
            messaging.edi_config_sync.queue.arn,
            messaging.edi_data_plane_jobs.queue.arn,
            messaging.edi_control_plane_jobs.queue.arn,
            messaging.edi_priority_notifications.queue.arn,
        ).apply(
            lambda a: [
                {
                    "Sid": "AS2ServerS3PayloadAccess",
                    "Effect": "Allow",
                    "Action": ["s3:PutObject", "s3:GetObject"],
                    "Resource": f"{a[0]}/*",
                },
                {
                    "Sid": "AS2ServerSNSPublish",
                    "Effect": "Allow",
                    "Action": ["sns:Publish"],
                    "Resource": a[1],
                },
                {
                    "Sid": "AS2ServerSQSEnqueue",
                    "Effect": "Allow",
                    "Action": ["sqs:SendMessage"],
                    "Resource": [a[2], a[3], a[4], a[5], a[6], a[7], a[8]],
                },
            ]
        )
        as2_task_role = _make_task_role("as2-server", as2_extra)
        as2_spec = _ServiceSpec(
            logical_name="as2-server",
            command=[
                "uvicorn",
                "as2_server.main:app",
                "--host",
                # S104 flags 0.0.0.0 as a dangerous binding to all interfaces.
                # However, this is required inside a Docker/ECS container for the ALB to route traffic.
                "0.0.0.0",  # noqa: S104
                "--port",
                "8000",
                "--workers",
                config.require("as2_server_workers"),
            ],
            cpu=config.require("as2_server_cpu"),
            memory=config.require("as2_server_memory"),
            desired_count=config.require_int("as2_server_replicas"),
            task_role=as2_task_role,
            port=8000,
        )
        as2_resources = _provision_service(
            spec=as2_spec,
            cluster=cluster,
            execution_role=execution_role,
            image_uri=image_uri,
            log_group=log_group,
            net=net,
            load_balancers=[
                aws.ecs.ServiceLoadBalancerArgs(
                    target_group_arn=as2_tg.arn,
                    container_name="as2-server",
                    container_port=8000,
                )
            ],
        )
        # Suppress unused variable warning — kept for explicit service graph reference.
        _ = as2_resources

        # ── edi-background-worker ──────────────────────────────────────────
        # Consumes control-plane + data-plane job queues.
        bg_extra: pulumi.Output[list[dict[str, object]]] = pulumi.Output.all(
            messaging.edi_control_plane_jobs.queue.arn,
            messaging.edi_control_plane_jobs.dlq.arn,
            messaging.edi_data_plane_jobs.queue.arn,
            messaging.edi_data_plane_jobs.dlq.arn,
            messaging.edi_events_topic.arn,
        ).apply(
            lambda a: [
                {
                    "Sid": "BGWorkerSQSConsume",
                    "Effect": "Allow",
                    "Action": [
                        "sqs:ReceiveMessage",
                        "sqs:DeleteMessage",
                        "sqs:ChangeMessageVisibility",
                        "sqs:GetQueueAttributes",
                    ],
                    "Resource": [a[0], a[1], a[2], a[3]],
                },
                {
                    "Sid": "BGWorkerSNSPublish",
                    "Effect": "Allow",
                    "Action": ["sns:Publish"],
                    "Resource": a[4],
                },
            ]
        )
        bg_task_role = _make_task_role("background-worker", bg_extra)
        _provision_service(
            spec=_ServiceSpec(
                logical_name="background-worker",
                command=["python", "-m", "edi_background_worker.main"],
                cpu=config.require("background_worker_cpu"),
                memory=config.require("background_worker_memory"),
                desired_count=1,
                task_role=bg_task_role,
            ),
            cluster=cluster,
            execution_role=execution_role,
            image_uri=image_uri,
            log_group=log_group,
            net=net,
        )

        # ── edi-compute-worker ─────────────────────────────────────────────
        # Transforms EDI documents; reads/writes S3 payloads.
        compute_extra: pulumi.Output[list[dict[str, object]]] = pulumi.Output.all(
            messaging.edi_transform.queue.arn,
            messaging.edi_transform.dlq.arn,
            storage.edi_payloads.arn,
        ).apply(
            lambda a: [
                {
                    "Sid": "ComputeWorkerSQSConsume",
                    "Effect": "Allow",
                    "Action": [
                        "sqs:ReceiveMessage",
                        "sqs:DeleteMessage",
                        "sqs:ChangeMessageVisibility",
                        "sqs:GetQueueAttributes",
                    ],
                    "Resource": [a[0], a[1]],
                },
                {
                    "Sid": "ComputeWorkerS3PayloadAccess",
                    "Effect": "Allow",
                    "Action": ["s3:GetObject", "s3:PutObject"],
                    "Resource": f"{a[2]}/*",
                },
            ]
        )
        compute_task_role = _make_task_role("compute-worker", compute_extra)
        _provision_service(
            spec=_ServiceSpec(
                logical_name="compute-worker",
                command=["python", "-m", "compute_worker.main"],
                cpu=config.require("compute_worker_cpu"),
                memory=config.require("compute_worker_memory"),
                desired_count=config.require_int("compute_worker_replicas"),
                task_role=compute_task_role,
            ),
            cluster=cluster,
            execution_role=execution_role,
            image_uri=image_uri,
            log_group=log_group,
            net=net,
        )

        # ── edi-orchestrator-worker ────────────────────────────────────────
        # Drives the EDI lifecycle state machine.
        orch_extra: pulumi.Output[list[dict[str, object]]] = pulumi.Output.all(
            messaging.edi_lifecycle.queue.arn,
            messaging.edi_lifecycle.dlq.arn,
        ).apply(
            lambda a: [
                {
                    "Sid": "OrchestratorWorkerSQSConsume",
                    "Effect": "Allow",
                    "Action": [
                        "sqs:ReceiveMessage",
                        "sqs:DeleteMessage",
                        "sqs:ChangeMessageVisibility",
                        "sqs:GetQueueAttributes",
                    ],
                    "Resource": [a[0], a[1]],
                }
            ]
        )
        orch_task_role = _make_task_role("orchestrator-worker", orch_extra)
        _provision_service(
            spec=_ServiceSpec(
                logical_name="orchestrator-worker",
                command=["python", "-m", "worker.main"],
                cpu=config.require("orchestrator_worker_cpu"),
                memory=config.require("orchestrator_worker_memory"),
                desired_count=1,
                task_role=orch_task_role,
            ),
            cluster=cluster,
            execution_role=execution_role,
            image_uri=image_uri,
            log_group=log_group,
            net=net,
        )

        # ── edi-config-sync-worker ─────────────────────────────────────────
        # Provisions AS2 partner configurations on new tenant onboarding events.
        sync_extra: pulumi.Output[list[dict[str, object]]] = pulumi.Output.all(
            messaging.edi_config_sync.queue.arn,
            messaging.edi_config_sync.dlq.arn,
        ).apply(
            lambda a: [
                {
                    "Sid": "ConfigSyncWorkerSQSConsume",
                    "Effect": "Allow",
                    "Action": [
                        "sqs:ReceiveMessage",
                        "sqs:DeleteMessage",
                        "sqs:ChangeMessageVisibility",
                        "sqs:GetQueueAttributes",
                    ],
                    "Resource": [a[0], a[1]],
                }
            ]
        )
        sync_task_role = _make_task_role("config-sync-worker", sync_extra)
        _provision_service(
            spec=_ServiceSpec(
                logical_name="config-sync-worker",
                command=["python", "-m", "config_sync_worker.provision.main"],
                cpu=config.require("config_sync_worker_cpu"),
                memory=config.require("config_sync_worker_memory"),
                desired_count=1,
                task_role=sync_task_role,
            ),
            cluster=cluster,
            execution_role=execution_role,
            image_uri=image_uri,
            log_group=log_group,
            net=net,
        )
