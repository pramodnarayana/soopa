"""
Seedwork (IaC Core Primitives)
"""

from infra_seedwork.autoscaling import (
    AutoScalingBounds,
    CpuUtilizationTrackingConfig,
    MemoryUtilizationTrackingConfig,
    ServiceAutoScalingConfig,
    configure_ecs_service_autoscaling,
    load_autoscaling_config_from_pulumi,
)
from infra_seedwork.constants import (
    DatabaseConstants,
    LogRetentionPolicy,
    ObservabilityDefaults,
    S3Constants,
    validate_log_retention,
)
from infra_seedwork.ecr import attach_ecr_lifecycle_policy, build_ecr_lifecycle_policy_doc
from infra_seedwork.ecs import (
    ContainerDefinition,
    ContainerDependency,
    EnvironmentVariable,
    FirelensConfiguration,
    HealthCheck,
    IamPolicyStatement,
    LogConfiguration,
    MountPoint,
    PortMapping,
    SecretVariable,
    TargetGroupConfig,
)
from infra_seedwork.env import (
    StackEnvironment,
)
from infra_seedwork.storage import (
    attach_bucket_lifecycle_configuration,
    build_account_scoped_bucket_name,
    provision_secure_bucket,
)

__all__ = [
    "AutoScalingBounds",
    "ContainerDefinition",
    "ContainerDependency",
    "CpuUtilizationTrackingConfig",
    "DatabaseConstants",
    "EnvironmentVariable",
    "FirelensConfiguration",
    "HealthCheck",
    "IamPolicyStatement",
    "LogConfiguration",
    "LogRetentionPolicy",
    "MemoryUtilizationTrackingConfig",
    "MountPoint",
    "ObservabilityDefaults",
    "PortMapping",
    "S3Constants",
    "SecretVariable",
    "ServiceAutoScalingConfig",
    "StackEnvironment",
    "TargetGroupConfig",
    "attach_bucket_lifecycle_configuration",
    "attach_ecr_lifecycle_policy",
    "build_account_scoped_bucket_name",
    "build_ecr_lifecycle_policy_doc",
    "configure_ecs_service_autoscaling",
    "load_autoscaling_config_from_pulumi",
    "provision_secure_bucket",
    "validate_log_retention",
]
