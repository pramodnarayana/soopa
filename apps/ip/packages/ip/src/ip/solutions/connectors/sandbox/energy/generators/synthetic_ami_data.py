"""Deterministic high-fidelity synthetic data generator for Smart Grid AMI physics.

Models ANSI C12.19, IEC 61968-9 (CIM), and NAESB ESPI (Green Button) interval
meter readings and electric distribution grid service point topologies.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from seedwork.domain.types import JsonDict

_STATUS_ACTIVE: Final[str] = "ACTIVE"
_QUALITY_VALIDATED: Final[str] = "VALIDATED"
_QUALITY_ESTIMATED: Final[str] = "ESTIMATED"

_DEFAULT_REGIONS: Final[tuple[str, ...]] = (
    "ERCOT_CENTRAL",
    "PJM_EAST",
    "CAISO_SOUTH",
    "MISO_NORTH",
    "NYISO_CAPITAL",
)

_STREET_NAMES: Final[tuple[str, ...]] = (
    "Redwood Dr",
    "Evergreen Terr",
    "Maple Ave",
    "Highland Way",
    "Cedar Blvd",
    "Oak Ridge Ln",
    "Pinehurst Ct",
    "Willow Creek Rd",
)


@dataclass(frozen=True)
class SimulatedServicePoint:
    """Represents a physical electric utility service point delivery location."""

    service_point_id: str
    meter_serial: str
    customer_id: str
    service_address: str
    grid_region: str
    status: str

    def to_dict(self) -> JsonDict:
        return {
            "service_point_id": self.service_point_id,
            "meter_serial": self.meter_serial,
            "customer_id": self.customer_id,
            "service_address": self.service_address,
            "grid_region": self.grid_region,
            "status": self.status,
        }


@dataclass(frozen=True)
class SimulatedIntervalReading:
    """Represents a 15-minute interval smart meter measurement payload."""

    meter_serial: str
    timestamp: str  # ISO-8601 UTC string
    interval_minutes: int
    kwh_delivered: float
    kwh_received: float
    voltage_avg: float
    quality: str
    service_point_id: str

    def to_dict(self) -> JsonDict:
        return {
            "meter_serial": self.meter_serial,
            "timestamp": self.timestamp,
            "interval_minutes": self.interval_minutes,
            "kwh_delivered": self.kwh_delivered,
            "kwh_received": self.kwh_received,
            "voltage_avg": self.voltage_avg,
            "quality": self.quality,
            "service_point_id": self.service_point_id,
        }


class SyntheticAmiDataGenerator:
    """Generates realistic diurnal electric load profiles and grid topology structures."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)  # noqa: S311 - Deterministic pseudo-randomness for synthetic AMI interval simulation, non-cryptographic

    def generate_service_points(self, count: int = 5) -> list[SimulatedServicePoint]:
        """Generates a deterministic topology of electric service points and assigned meters."""
        service_points: list[SimulatedServicePoint] = []
        for i in range(1, max(1, count) + 1):
            sp_id = f"SP-{i:05d}"
            meter_serial = f"MTR-{9000000 + i}"
            cust_id = f"CUST-{40000 + i}"
            street = _STREET_NAMES[(i - 1) % len(_STREET_NAMES)]
            address = f"{100 * i + 42} {street}, Gridville, TX 7870{i % 9}"
            region = _DEFAULT_REGIONS[(i - 1) % len(_DEFAULT_REGIONS)]
            service_points.append(
                SimulatedServicePoint(
                    service_point_id=sp_id,
                    meter_serial=meter_serial,
                    customer_id=cust_id,
                    service_address=address,
                    grid_region=region,
                    status=_STATUS_ACTIVE,
                )
            )
        return service_points

    @staticmethod
    def _diurnal_load_factor(hour: float) -> float:
        """Computes diurnal normalized residential power demand (0.2kW baseline to ~3.8kW peak).

        Two prominent daily peaks:
        1. Morning peak around 07:30 - 08:30 (breakfast, heating/appliances).
        2. Evening peak around 18:30 - 21:00 (cooking, EV charging, HVAC).
        """
        # Base overnight quiescent load
        base = 0.25

        # Morning peak Gaussian bell centered at 8.0 with width 1.5
        morning_peak = 1.8 * math.exp(-0.5 * ((hour - 8.0) / 1.5) ** 2)

        # Evening peak Gaussian bell centered at 19.5 with width 2.0
        evening_peak = 3.2 * math.exp(-0.5 * ((hour - 19.5) / 2.0) ** 2)

        # Midday plateau
        midday_plateau = 0.6 * math.exp(-0.5 * ((hour - 13.0) / 3.0) ** 2)

        return base + morning_peak + evening_peak + midday_plateau

    def generate_interval_readings(
        self,
        service_points: list[SimulatedServicePoint],
        intervals_per_meter: int = 24,
        *,
        base_time: datetime | None = None,
        failure_rate_percent: float = 0.0,
    ) -> list[SimulatedIntervalReading]:
        """Generates synchronized 15-minute interval readings for all given service points."""
        readings: list[SimulatedIntervalReading] = []
        now = base_time or datetime.now(UTC)

        # Align to the nearest preceding 15-minute boundary
        minute_floor = (now.minute // 15) * 15
        aligned_end = now.replace(minute=minute_floor, second=0, microsecond=0)

        # Generate timestamps stepping backwards
        timestamps: list[datetime] = [
            aligned_end - timedelta(minutes=15 * step)
            for step in range(max(1, intervals_per_meter) - 1, -1, -1)
        ]

        failure_threshold = max(0.0, min(100.0, failure_rate_percent)) / 100.0

        for ts in timestamps:
            hour_float = ts.hour + (ts.minute / 60.0)
            nominal_kw = self._diurnal_load_factor(hour_float)

            for sp in service_points:
                # Add household-specific variance (+/- 15%)
                household_jitter = self._rng.uniform(0.85, 1.15)
                # Add interval measurement noise (+/- 5%)
                noise = self._rng.uniform(0.95, 1.05)
                kw = max(0.05, nominal_kw * household_jitter * noise)

                # 15-minute kWh is kW * (15 / 60)
                kwh_delivered = round(kw * 0.25, 4)

                # Solar net metering (simulate distributed generation for 20% of meters around midday)
                is_solar_meter = (int(sp.meter_serial.replace("MTR-", "")) % 5) == 0
                kwh_received = 0.0
                if is_solar_meter and 10.0 <= hour_float <= 15.0:
                    solar_gen_kw = 4.0 * math.exp(-0.5 * ((hour_float - 12.5) / 1.8) ** 2)
                    solar_kwh = round(solar_gen_kw * 0.25 * self._rng.uniform(0.9, 1.1), 4)
                    if solar_kwh > kwh_delivered:
                        kwh_received = round(solar_kwh - kwh_delivered, 4)
                        kwh_delivered = 0.0
                    else:
                        kwh_delivered = round(kwh_delivered - solar_kwh, 4)

                # Grid voltage centered at 120.0V RMS with normal variance (+/- 1.5V)
                voltage_avg = round(self._rng.gauss(120.2, 1.1), 2)

                # Data quality flag
                quality = _QUALITY_VALIDATED
                if failure_threshold > 0.0 and self._rng.random() < failure_threshold:
                    quality = _QUALITY_ESTIMATED
                    voltage_avg = round(voltage_avg * 0.92, 2)  # Simulate voltage sag

                readings.append(
                    SimulatedIntervalReading(
                        meter_serial=sp.meter_serial,
                        timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        interval_minutes=15,
                        kwh_delivered=kwh_delivered,
                        kwh_received=kwh_received,
                        voltage_avg=voltage_avg,
                        quality=quality,
                        service_point_id=sp.service_point_id,
                    )
                )

        return readings
