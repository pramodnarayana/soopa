"""
Unit Tests for Auto Scaling Seedwork Module
==========================================
Verifies typed AutoScalingBounds validation, default configuration parameters,
and declarative loading from Pulumi configuration using pure fake objects (no mocks).
"""

import pytest
from infra_seedwork import (
    AutoScalingBounds,
    CpuUtilizationTrackingConfig,
    MemoryUtilizationTrackingConfig,
    ServiceAutoScalingConfig,
    configure_ecs_service_autoscaling,
    load_autoscaling_config_from_pulumi,
)


class FakePulumiConfig:
    """Pure test double replacing unittest.mock to adhere to enterprise standards."""

    def __init__(
        self,
        bools: dict[str, bool] | None = None,
        ints: dict[str, int] | None = None,
        floats: dict[str, float] | None = None,
    ) -> None:
        self._bools = bools or {}
        self._ints = ints or {}
        self._floats = floats or {}

    def get_bool(self, key: str) -> bool | None:
        return self._bools.get(key)

    def get_int(self, key: str) -> int | None:
        return self._ints.get(key)

    def get_float(self, key: str) -> float | None:
        return self._floats.get(key)


def test_autoscaling_bounds_valid_defaults() -> None:
    bounds = AutoScalingBounds()
    assert bounds.min_capacity == 1
    assert bounds.max_capacity == 4


def test_autoscaling_bounds_valid_custom() -> None:
    bounds = AutoScalingBounds(min_capacity=2, max_capacity=8)
    assert bounds.min_capacity == 2
    assert bounds.max_capacity == 8


def test_autoscaling_bounds_rejects_min_less_than_one() -> None:
    with pytest.raises(ValueError, match="min_capacity must be at least 1"):
        AutoScalingBounds(min_capacity=0, max_capacity=4)


def test_autoscaling_bounds_rejects_max_less_than_min() -> None:
    with pytest.raises(ValueError, match="cannot be less than min_capacity"):
        AutoScalingBounds(min_capacity=4, max_capacity=2)


def test_cpu_utilization_tracking_defaults() -> None:
    config = CpuUtilizationTrackingConfig()
    assert config.target_value == 70.0
    assert config.scale_in_cooldown == 300
    assert config.scale_out_cooldown == 60


def test_memory_utilization_tracking_defaults() -> None:
    config = MemoryUtilizationTrackingConfig()
    assert config.target_value == 75.0
    assert config.scale_in_cooldown == 300
    assert config.scale_out_cooldown == 60


def test_service_autoscaling_config_defaults() -> None:
    config = ServiceAutoScalingConfig()
    assert config.enabled is False
    assert config.bounds.min_capacity == 1
    assert config.bounds.max_capacity == 4
    assert config.cpu_tracking is not None
    assert config.cpu_tracking.target_value == 70.0


def test_load_autoscaling_config_disabled_by_default() -> None:
    fake_config = FakePulumiConfig()

    parsed = load_autoscaling_config_from_pulumi(fake_config)
    assert parsed.enabled is False
    assert parsed.bounds.min_capacity == 1
    assert parsed.bounds.max_capacity == 4
    assert parsed.cpu_tracking is not None
    assert parsed.cpu_tracking.target_value == 70.0


def test_load_autoscaling_config_enabled_with_custom_values() -> None:
    fake_config = FakePulumiConfig(
        bools={"enable_autoscaling": True},
        ints={"min_capacity": 2, "max_capacity": 6},
        floats={"target_cpu_percent": 65.0, "target_memory_percent": 80.0},
    )

    parsed = load_autoscaling_config_from_pulumi(fake_config)
    assert parsed.enabled is True
    assert parsed.bounds.min_capacity == 2
    assert parsed.bounds.max_capacity == 6
    assert parsed.cpu_tracking is not None
    assert parsed.cpu_tracking.target_value == 65.0
    assert parsed.memory_tracking is not None
    assert parsed.memory_tracking.target_value == 80.0


def test_configure_ecs_service_autoscaling_noop_when_disabled() -> None:
    config = ServiceAutoScalingConfig(enabled=False)
    target, policies = configure_ecs_service_autoscaling(
        name="test-svc",
        cluster_name="test-cluster",
        service_name="test-service",
        config=config,
    )
    assert target is None
    assert policies == []


@pytest.mark.parametrize("invalid_val", [0.0, -10.0, 100.1, 150.0, float("nan"), float("inf")])
def test_cpu_utilization_tracking_rejects_invalid_target_value(invalid_val: float) -> None:
    with pytest.raises(ValueError, match="target_value must be a finite percentage in"):
        CpuUtilizationTrackingConfig(target_value=invalid_val)


@pytest.mark.parametrize("invalid_val", [0.0, -5.0, 100.5, 200.0, float("nan"), float("inf")])
def test_memory_utilization_tracking_rejects_invalid_target_value(invalid_val: float) -> None:
    with pytest.raises(ValueError, match="target_value must be a finite percentage in"):
        MemoryUtilizationTrackingConfig(target_value=invalid_val)


def test_utilization_tracking_rejects_negative_cooldowns() -> None:
    with pytest.raises(ValueError, match="scale_in_cooldown must be non-negative"):
        CpuUtilizationTrackingConfig(scale_in_cooldown=-1)
    with pytest.raises(ValueError, match="scale_out_cooldown must be non-negative"):
        CpuUtilizationTrackingConfig(scale_out_cooldown=-1)
    with pytest.raises(ValueError, match="scale_in_cooldown must be non-negative"):
        MemoryUtilizationTrackingConfig(scale_in_cooldown=-1)
    with pytest.raises(ValueError, match="scale_out_cooldown must be non-negative"):
        MemoryUtilizationTrackingConfig(scale_out_cooldown=-1)


def test_load_autoscaling_config_preserves_zero_min_capacity_for_validation() -> None:
    fake_config = FakePulumiConfig(ints={"min_capacity": 0})
    with pytest.raises(ValueError, match="min_capacity must be at least 1"):
        load_autoscaling_config_from_pulumi(fake_config)


def test_load_autoscaling_config_preserves_zero_cpu_target_for_validation() -> None:
    fake_config = FakePulumiConfig(floats={"target_cpu_percent": 0.0})
    with pytest.raises(ValueError, match="target_value must be a finite percentage in"):
        load_autoscaling_config_from_pulumi(fake_config)
