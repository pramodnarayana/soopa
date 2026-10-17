"""
Auto Scaling Seedwork Module (Enterprise Grade)
==============================================
Provides strongly-typed, domain-agnostic primitives for registering ECS Fargate services
with AWS Application Auto Scaling and attaching target tracking scaling policies.
"""

import math
from dataclasses import dataclass
from typing import Protocol

import pulumi
import pulumi_aws as aws


class ConfigReader(Protocol):
    """Protocol for reading configuration keys, supporting both Pulumi and test doubles."""

    def get_bool(self, key: str) -> bool | None: ...

    def get_int(self, key: str) -> int | None: ...

    def get_float(self, key: str) -> float | None: ...


@dataclass(frozen=True)
class AutoScalingBounds:
    """Defines the lower and upper bounds of task capacity."""

    min_capacity: int = 1
    max_capacity: int = 4

    def __post_init__(self) -> None:
        if self.min_capacity < 1:
            raise ValueError(f"min_capacity must be at least 1, got {self.min_capacity}")
        if self.max_capacity < self.min_capacity:
            raise ValueError(
                f"max_capacity ({self.max_capacity}) cannot be less than min_capacity ({self.min_capacity})"
            )


@dataclass(frozen=True)
class CpuUtilizationTrackingConfig:
    """Configures target tracking scaling based on average CPU utilization."""

    target_value: float = 70.0
    scale_in_cooldown: int = 300
    scale_out_cooldown: int = 60

    def __post_init__(self) -> None:
        if not math.isfinite(self.target_value) or not (0 < self.target_value <= 100):
            raise ValueError(
                f"target_value must be a finite percentage in (0, 100], got {self.target_value}"
            )
        if self.scale_in_cooldown < 0:
            raise ValueError(
                f"scale_in_cooldown must be non-negative, got {self.scale_in_cooldown}"
            )
        if self.scale_out_cooldown < 0:
            raise ValueError(
                f"scale_out_cooldown must be non-negative, got {self.scale_out_cooldown}"
            )


@dataclass(frozen=True)
class MemoryUtilizationTrackingConfig:
    """Configures target tracking scaling based on average Memory utilization."""

    target_value: float = 75.0
    scale_in_cooldown: int = 300
    scale_out_cooldown: int = 60

    def __post_init__(self) -> None:
        if not math.isfinite(self.target_value) or not (0 < self.target_value <= 100):
            raise ValueError(
                f"target_value must be a finite percentage in (0, 100], got {self.target_value}"
            )
        if self.scale_in_cooldown < 0:
            raise ValueError(
                f"scale_in_cooldown must be non-negative, got {self.scale_in_cooldown}"
            )
        if self.scale_out_cooldown < 0:
            raise ValueError(
                f"scale_out_cooldown must be non-negative, got {self.scale_out_cooldown}"
            )


@dataclass(frozen=True)
class ServiceAutoScalingConfig:
    """Composite configuration for an ECS service auto-scaling lifecycle."""

    enabled: bool = False
    bounds: AutoScalingBounds = AutoScalingBounds()
    cpu_tracking: CpuUtilizationTrackingConfig | None = CpuUtilizationTrackingConfig()
    memory_tracking: MemoryUtilizationTrackingConfig | None = MemoryUtilizationTrackingConfig()


def load_autoscaling_config_from_pulumi(
    config: ConfigReader,
    prefix: str = "",
) -> ServiceAutoScalingConfig:
    """
    Parses ServiceAutoScalingConfig declaratively from Pulumi configuration.

    Guarantees no hardcoded binary environment branching in application stacks.
    """
    pfx = f"{prefix}_" if prefix and not prefix.endswith("_") else prefix
    key_enabled = f"{pfx}enable_autoscaling" if pfx else "enable_autoscaling"
    key_min = f"{pfx}min_capacity" if pfx else "min_capacity"
    key_max = f"{pfx}max_capacity" if pfx else "max_capacity"
    key_cpu = f"{pfx}target_cpu_percent" if pfx else "target_cpu_percent"
    key_mem = f"{pfx}target_memory_percent" if pfx else "target_memory_percent"

    enabled_val = config.get_bool(key_enabled)
    enabled = enabled_val if enabled_val is not None else False

    min_cap_val = config.get_int(key_min)
    min_cap = min_cap_val if min_cap_val is not None else 1

    max_cap_val = config.get_int(key_max)
    max_cap = max_cap_val if max_cap_val is not None else 4

    cpu_target_val = config.get_float(key_cpu)
    cpu_target = cpu_target_val if cpu_target_val is not None else 70.0

    mem_target_val = config.get_float(key_mem)
    mem_target = mem_target_val if mem_target_val is not None else 75.0

    return ServiceAutoScalingConfig(
        enabled=enabled,
        bounds=AutoScalingBounds(min_capacity=min_cap, max_capacity=max_cap),
        cpu_tracking=CpuUtilizationTrackingConfig(target_value=cpu_target),
        memory_tracking=MemoryUtilizationTrackingConfig(target_value=mem_target),
    )


def configure_ecs_service_autoscaling(
    name: str,
    cluster_name: pulumi.Input[str],
    service_name: pulumi.Input[str],
    config: ServiceAutoScalingConfig,
    tags: dict[str, str] | None = None,
) -> tuple[aws.appautoscaling.Target | None, list[aws.appautoscaling.Policy]]:
    """
    Registers an ECS service with AWS Application Auto Scaling and creates
    CPU and Memory target tracking policies based on declarative configuration.

    Returns:
        tuple containing (Target | None, list[Policy])
    """
    if not config.enabled:
        return None, []

    resource_id = pulumi.Output.concat("service/", cluster_name, "/", service_name)

    target = aws.appautoscaling.Target(
        f"{name}-scaling-target",
        max_capacity=config.bounds.max_capacity,
        min_capacity=config.bounds.min_capacity,
        resource_id=resource_id,
        scalable_dimension="ecs:service:DesiredCount",
        service_namespace="ecs",
        tags=tags,
    )

    policies: list[aws.appautoscaling.Policy] = []

    if config.cpu_tracking:
        cpu_policy = aws.appautoscaling.Policy(
            f"{name}-cpu-scaling-policy",
            policy_type="TargetTrackingScaling",
            resource_id=target.resource_id,
            scalable_dimension=target.scalable_dimension,
            service_namespace=target.service_namespace,
            target_tracking_scaling_policy_configuration=aws.appautoscaling.PolicyTargetTrackingScalingPolicyConfigurationArgs(
                target_value=config.cpu_tracking.target_value,
                scale_in_cooldown=config.cpu_tracking.scale_in_cooldown,
                scale_out_cooldown=config.cpu_tracking.scale_out_cooldown,
                predefined_metric_specification=aws.appautoscaling.PolicyTargetTrackingScalingPolicyConfigurationPredefinedMetricSpecificationArgs(
                    predefined_metric_type="ECSServiceAverageCPUUtilization",
                ),
            ),
        )
        policies.append(cpu_policy)

    if config.memory_tracking:
        mem_policy = aws.appautoscaling.Policy(
            f"{name}-mem-scaling-policy",
            policy_type="TargetTrackingScaling",
            resource_id=target.resource_id,
            scalable_dimension=target.scalable_dimension,
            service_namespace=target.service_namespace,
            target_tracking_scaling_policy_configuration=aws.appautoscaling.PolicyTargetTrackingScalingPolicyConfigurationArgs(
                target_value=config.memory_tracking.target_value,
                scale_in_cooldown=config.memory_tracking.scale_in_cooldown,
                scale_out_cooldown=config.memory_tracking.scale_out_cooldown,
                predefined_metric_specification=aws.appautoscaling.PolicyTargetTrackingScalingPolicyConfigurationPredefinedMetricSpecificationArgs(
                    predefined_metric_type="ECSServiceAverageMemoryUtilization",
                ),
            ),
        )
        policies.append(mem_policy)

    return target, policies
