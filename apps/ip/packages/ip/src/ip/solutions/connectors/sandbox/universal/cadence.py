"""Concrete Push Cadence Strategies and Strategy Factory for the Universal Schema Simulator."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from ip.engine.domain.exceptions import InvalidConnectionConfigError
from ip.solutions.connectors.sandbox.universal.strategies import (
    CadenceState,
    PushCadenceMode,
    PushCadenceStrategy,
)
from seedwork.domain.types import JsonValue


@dataclass(frozen=True)
class ManualCadenceStrategy:
    """Manual on-demand emission strategy triggered strictly on user request."""

    records_per_push: int = 1

    def __post_init__(self) -> None:
        if self.records_per_push < 1:
            object.__setattr__(self, "records_per_push", 1)

    def compute_next_delay_seconds(self, state: CadenceState) -> float:
        _ = state
        return 0.0

    def compute_batch_size(self, state: CadenceState) -> int:
        _ = state
        return max(1, self.records_per_push)

    def should_emit(self, state: CadenceState) -> bool:
        _ = state
        return True


@dataclass(frozen=True)
class ConstantPacedCadenceStrategy:
    """Fixed-rate emission strategy pacing uniform inter-arrival intervals."""

    messages_per_second: float = 1.0

    def __post_init__(self) -> None:
        if self.messages_per_second <= 0.0:
            object.__setattr__(self, "messages_per_second", 1.0)

    def compute_next_delay_seconds(self, state: CadenceState) -> float:
        _ = state
        return 1.0 / self.messages_per_second

    def compute_batch_size(self, state: CadenceState) -> int:
        _ = state
        return 1

    def should_emit(self, state: CadenceState) -> bool:
        _ = state
        return True


@dataclass(frozen=True)
class RandomBurstCadenceStrategy:
    """Fixed-interval emission strategy delivering pseudo-random burst batch sizes."""

    min_batch: int = 1
    max_batch: int = 10
    interval_seconds: float = 5.0
    seed: int = 42

    def compute_next_delay_seconds(self, state: CadenceState) -> float:
        _ = state
        return max(0.01, self.interval_seconds)

    def compute_batch_size(self, state: CadenceState) -> int:
        prng = random.Random(  # noqa: S311 - Non-cryptographic PRNG required for deterministic simulation
            self.seed + state.cycle_index
        )
        low = min(self.min_batch, self.max_batch)
        high = max(self.min_batch, self.max_batch)
        return prng.randint(max(1, low), max(1, high))

    def should_emit(self, state: CadenceState) -> bool:
        _ = state
        return True


@dataclass(frozen=True)
class PoissonJitterCadenceStrategy:
    """Stochastic inter-arrival delays and variable batch sizes simulating human/system jitter."""

    min_delay_seconds: float = 1.0
    max_delay_seconds: float = 10.0
    min_batch: int = 1
    max_batch: int = 5
    seed: int = 42

    def compute_next_delay_seconds(self, state: CadenceState) -> float:
        prng = random.Random(  # noqa: S311 - Non-cryptographic PRNG required for deterministic simulation
            self.seed + state.cycle_index
        )
        low = min(self.min_delay_seconds, self.max_delay_seconds)
        high = max(self.min_delay_seconds, self.max_delay_seconds)
        return max(0.001, prng.uniform(low, high))

    def compute_batch_size(self, state: CadenceState) -> int:
        prng = random.Random(  # noqa: S311 - Non-cryptographic PRNG required for deterministic simulation
            (self.seed >> 4) + state.cycle_index
        )
        low = min(self.min_batch, self.max_batch)
        high = max(self.min_batch, self.max_batch)
        return prng.randint(max(1, low), max(1, high))

    def should_emit(self, state: CadenceState) -> bool:
        _ = state
        return True


@dataclass(frozen=True)
class DiurnalWaveCadenceStrategy:
    """Circadian sinusoidal rate modulation based on UTC hour to simulate day/night activity."""

    base_rate_per_second: float = 1.0
    peak_multiplier: float = 5.0
    peak_hour_utc: int = 14

    def compute_next_delay_seconds(self, state: CadenceState) -> float:
        now = (
            state.last_emitted_at.astimezone(UTC) if state.last_emitted_at else datetime.now(tz=UTC)
        )
        seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
        peak_seconds = self.peak_hour_utc * 3600

        phase = (seconds_since_midnight - peak_seconds) / 86400.0 * 2.0 * math.pi
        normalized_wave = (math.cos(phase) + 1.0) / 2.0
        current_rate = self.base_rate_per_second * (
            1.0 + (self.peak_multiplier - 1.0) * normalized_wave
        )
        return 1.0 / max(0.01, current_rate)

    def compute_batch_size(self, state: CadenceState) -> int:
        _ = state
        return 1

    def should_emit(self, state: CadenceState) -> bool:
        _ = state
        return True


@dataclass(frozen=True)
class CronBatchCadenceStrategy:
    """Scheduled macro-batch releases mimicking scheduled enterprise exports."""

    interval_seconds: float = 3600.0
    batch_size: int = 500
    cron_expression: str | None = None

    def compute_next_delay_seconds(self, state: CadenceState) -> float:
        _ = state
        return max(1.0, self.interval_seconds)

    def compute_batch_size(self, state: CadenceState) -> int:
        _ = state
        return max(1, self.batch_size)

    def should_emit(self, state: CadenceState) -> bool:
        _ = state
        return True


@dataclass(frozen=True)
class ThinPushCadenceStrategy:
    """Paced notifications emitting single notification pings requiring reverse pull."""

    interval_seconds: float = 2.0

    def compute_next_delay_seconds(self, state: CadenceState) -> float:
        _ = state
        return max(0.01, self.interval_seconds)

    def compute_batch_size(self, state: CadenceState) -> int:
        _ = state
        return 1

    def should_emit(self, state: CadenceState) -> bool:
        _ = state
        return True


@dataclass(frozen=True)
class ChaosFaultCadenceStrategy:
    """Cadence strategy injecting deliberate emission drops and latency."""

    base_interval_seconds: float = 1.0
    batch_size: int = 5
    drop_rate_percent: float = 20.0
    seed: int = 42

    def compute_next_delay_seconds(self, state: CadenceState) -> float:
        prng = random.Random(  # noqa: S311 - Non-cryptographic PRNG required for deterministic simulation
            self.seed + state.cycle_index
        )
        extra_latency = prng.uniform(0.0, 2.0) if (prng.random() * 100 < 30.0) else 0.0
        return self.base_interval_seconds + extra_latency

    def compute_batch_size(self, state: CadenceState) -> int:
        _ = state
        return max(1, self.batch_size)

    def should_emit(self, state: CadenceState) -> bool:
        prng = random.Random(  # noqa: S311 - Non-cryptographic PRNG required for deterministic simulation
            self.seed + (state.cycle_index * 7)
        )
        roll = prng.uniform(0.0, 100.0)
        return roll >= self.drop_rate_percent


def _extract_float(val: JsonValue | None, default: float) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return default
    return default


def _extract_int(val: JsonValue | None, default: int) -> int:
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str) and val.isdigit():
        return int(val)
    return default


def resolve_push_cadence_strategy(
    mode: PushCadenceMode,
    config: Mapping[str, JsonValue] | None = None,
) -> PushCadenceStrategy:
    """Factory resolving a strongly-typed PushCadenceStrategy from mode and scalar parameters."""
    cfg = config or {}

    if mode == PushCadenceMode.MANUAL:
        records = _extract_int(cfg.get("records_per_push"), 1)
        return ManualCadenceStrategy(records_per_push=records)

    if mode == PushCadenceMode.CONSTANT_PACED:
        rate = _extract_float(cfg.get("messages_per_second"), 1.0)
        return ConstantPacedCadenceStrategy(messages_per_second=rate)

    if mode == PushCadenceMode.RANDOM_BURST:
        min_b = _extract_int(cfg.get("min_batch"), 1)
        max_b = _extract_int(cfg.get("max_batch"), 10)
        interval = _extract_float(cfg.get("interval_seconds"), 5.0)
        seed = _extract_int(cfg.get("seed"), 42)
        return RandomBurstCadenceStrategy(
            min_batch=min_b,
            max_batch=max_b,
            interval_seconds=interval,
            seed=seed,
        )

    if mode == PushCadenceMode.POISSON_JITTER:
        min_d = _extract_float(cfg.get("min_delay_seconds"), 1.0)
        max_d = _extract_float(cfg.get("max_delay_seconds"), 10.0)
        min_b = _extract_int(cfg.get("min_batch"), 1)
        max_b = _extract_int(cfg.get("max_batch"), 5)
        seed = _extract_int(cfg.get("seed"), 42)
        return PoissonJitterCadenceStrategy(
            min_delay_seconds=min_d,
            max_delay_seconds=max_d,
            min_batch=min_b,
            max_batch=max_b,
            seed=seed,
        )

    if mode == PushCadenceMode.DIURNAL_WAVE:
        base_rate = _extract_float(cfg.get("base_rate_per_second"), 1.0)
        peak_mult = _extract_float(cfg.get("peak_multiplier"), 5.0)
        peak_hour = _extract_int(cfg.get("peak_hour_utc"), 14)
        return DiurnalWaveCadenceStrategy(
            base_rate_per_second=base_rate,
            peak_multiplier=peak_mult,
            peak_hour_utc=peak_hour,
        )

    if mode == PushCadenceMode.CRON_BATCH:
        interval = _extract_float(cfg.get("interval_seconds"), 3600.0)
        b_size = _extract_int(cfg.get("batch_size"), 500)
        cron_expr = cfg.get("cron_expression")
        return CronBatchCadenceStrategy(
            interval_seconds=interval,
            batch_size=b_size,
            cron_expression=str(cron_expr) if cron_expr is not None else None,
        )

    if mode == PushCadenceMode.THIN_PUSH:
        interval = _extract_float(cfg.get("interval_seconds"), 2.0)
        return ThinPushCadenceStrategy(interval_seconds=interval)

    if mode == PushCadenceMode.CHAOS_FAULT:
        base_int = _extract_float(cfg.get("base_interval_seconds"), 1.0)
        b_size = _extract_int(cfg.get("batch_size"), 5)
        drop_p = _extract_float(cfg.get("drop_rate_percent"), 20.0)
        seed = _extract_int(cfg.get("seed"), 42)
        return ChaosFaultCadenceStrategy(
            base_interval_seconds=base_int,
            batch_size=b_size,
            drop_rate_percent=drop_p,
            seed=seed,
        )

    return ConstantPacedCadenceStrategy()


def _validate_constant_paced_config(
    config: Mapping[str, JsonValue],
) -> InvalidConnectionConfigError | None:
    if "messages_per_second" in config:
        rate = config["messages_per_second"]
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0.0:
            return InvalidConnectionConfigError(
                field_name="push_config.messages_per_second",
                message="messages_per_second must be a positive number.",
                details={
                    "push_mode": PushCadenceMode.CONSTANT_PACED.value,
                    "messages_per_second": rate,
                },
            )
    return None


def _validate_random_burst_config(
    config: Mapping[str, JsonValue],
) -> InvalidConnectionConfigError | None:
    min_b = config.get("min_batch")
    max_b = config.get("max_batch")
    if min_b is not None and (not isinstance(min_b, int) or isinstance(min_b, bool) or min_b < 1):
        return InvalidConnectionConfigError(
            field_name="push_config.min_batch",
            message="min_batch must be a positive integer.",
            details={"push_mode": PushCadenceMode.RANDOM_BURST.value},
        )
    if max_b is not None and (not isinstance(max_b, int) or isinstance(max_b, bool) or max_b < 1):
        return InvalidConnectionConfigError(
            field_name="push_config.max_batch",
            message="max_batch must be a positive integer.",
            details={"push_mode": PushCadenceMode.RANDOM_BURST.value},
        )
    if (
        isinstance(min_b, int)
        and not isinstance(min_b, bool)
        and isinstance(max_b, int)
        and not isinstance(max_b, bool)
        and min_b > max_b
    ):
        return InvalidConnectionConfigError(
            field_name="push_config.min_batch",
            message="min_batch must be less than or equal to max_batch.",
            details={"push_mode": PushCadenceMode.RANDOM_BURST.value},
        )
    return None


def _validate_poisson_jitter_config(
    config: Mapping[str, JsonValue],
) -> InvalidConnectionConfigError | None:
    min_d = config.get("min_delay_seconds")
    max_d = config.get("max_delay_seconds")
    if min_d is not None and (
        not isinstance(min_d, (int, float)) or isinstance(min_d, bool) or min_d < 0.0
    ):
        return InvalidConnectionConfigError(
            field_name="push_config.min_delay_seconds",
            message="min_delay_seconds must be a non-negative number.",
            details={"push_mode": PushCadenceMode.POISSON_JITTER.value},
        )
    if max_d is not None and (
        not isinstance(max_d, (int, float)) or isinstance(max_d, bool) or max_d <= 0.0
    ):
        return InvalidConnectionConfigError(
            field_name="push_config.max_delay_seconds",
            message="max_delay_seconds must be a positive number.",
            details={"push_mode": PushCadenceMode.POISSON_JITTER.value},
        )
    if (
        isinstance(min_d, (int, float))
        and not isinstance(min_d, bool)
        and isinstance(max_d, (int, float))
        and not isinstance(max_d, bool)
        and min_d > max_d
    ):
        return InvalidConnectionConfigError(
            field_name="push_config.min_delay_seconds",
            message="min_delay_seconds cannot exceed max_delay_seconds.",
            details={"push_mode": PushCadenceMode.POISSON_JITTER.value},
        )
    return None


def _validate_cron_batch_config(
    config: Mapping[str, JsonValue],
) -> InvalidConnectionConfigError | None:
    cron_expr = config.get("cron_expression")
    if cron_expr is not None and (
        not isinstance(cron_expr, str) or len(cron_expr.strip().split()) != 5
    ):
        return InvalidConnectionConfigError(
            field_name="push_config.cron_expression",
            message="cron_expression must be a standard 5-field cron string.",
            details={"push_mode": PushCadenceMode.CRON_BATCH.value, "cron_expression": cron_expr},
        )
    return None


def _validate_chaos_fault_config(
    config: Mapping[str, JsonValue],
) -> InvalidConnectionConfigError | None:
    drop_p = config.get("drop_rate_percent")
    if drop_p is not None and (
        not isinstance(drop_p, (int, float))
        or isinstance(drop_p, bool)
        or drop_p < 0.0
        or drop_p > 100.0
    ):
        return InvalidConnectionConfigError(
            field_name="push_config.drop_rate_percent",
            message="drop_rate_percent must be between 0.0 and 100.0.",
            details={"push_mode": PushCadenceMode.CHAOS_FAULT.value},
        )
    return None


def _validate_manual_config(
    config: Mapping[str, JsonValue],
) -> InvalidConnectionConfigError | None:
    records = config.get("records_per_push")
    if records is not None and (
        not isinstance(records, int) or isinstance(records, bool) or records < 1
    ):
        return InvalidConnectionConfigError(
            field_name="push_config.records_per_push",
            message="records_per_push must be a positive integer.",
            details={"push_mode": PushCadenceMode.MANUAL.value},
        )
    return None


def validate_push_cadence_config(
    mode: PushCadenceMode,
    config: Mapping[str, JsonValue] | None = None,
) -> InvalidConnectionConfigError | None:
    """Validates cadence configuration parameters against mode-specific invariants."""
    if config is None:
        return None

    if mode == PushCadenceMode.MANUAL:
        return _validate_manual_config(config)
    if mode == PushCadenceMode.CONSTANT_PACED:
        return _validate_constant_paced_config(config)
    if mode == PushCadenceMode.RANDOM_BURST:
        return _validate_random_burst_config(config)
    if mode == PushCadenceMode.POISSON_JITTER:
        return _validate_poisson_jitter_config(config)
    if mode == PushCadenceMode.CRON_BATCH:
        return _validate_cron_batch_config(config)
    if mode == PushCadenceMode.CHAOS_FAULT:
        return _validate_chaos_fault_config(config)
    return None


__all__ = [
    "ChaosFaultCadenceStrategy",
    "ConstantPacedCadenceStrategy",
    "CronBatchCadenceStrategy",
    "DiurnalWaveCadenceStrategy",
    "ManualCadenceStrategy",
    "PoissonJitterCadenceStrategy",
    "RandomBurstCadenceStrategy",
    "ThinPushCadenceStrategy",
    "resolve_push_cadence_strategy",
    "validate_push_cadence_config",
]
