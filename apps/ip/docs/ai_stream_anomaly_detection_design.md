# System Architecture & Engineering Design: Semantic Data Quality & Stream Anomaly Detection

- **Document:** ARCH-IP-016 — Real-Time Stream Scoring, Baseline Profiling & Quarantine Architecture
- **Product:** Soopa Integration Platform (`apps/ip`)
- **Status:** Approved Architecture Specification (Gold Standard)
- **Bounded Context:** Ingestion & Real-Time Data Quality (`L1/L2 Streaming`)
- **Related Specs:** [ai_stream_anomaly_detection_prd.md](ai_stream_anomaly_detection_prd.md), [l1_ingestion_design.md](l1_ingestion_design.md)
- **Architecture Style:** Hexagonal Architecture • Two-Tier Vectorized Fast-Path • Asynchronous Baseline Learning

---

## 1. Architectural Philosophy: Two-Tier Anomaly Engine

To support streaming ingestion exceeding **100,000 records per second**, the system enforces a strict physical separation between **Fast-Path Real-Time Scoring** and **Offline Baseline Learning**:

```mermaid
flowchart TB
    subgraph OfflinePlane["Control Plane (Offline Asynchronous Baseline Learner)"]
        L2ReplicaHistory[("PostgreSQL: L2 Historical Replicas\n(14-day rolling window)")]
        BaselineTrainer["BaselineTrainerJob\n(Calculates Diurnal Mean, StdDev, IQR)"]
        RedisBaselineCache[("Redis Cluster / In-Memory Cache\n(Pre-compiled Weights per Feeder/Cluster)")]
    end

    subgraph FastPathPlane["Data Plane Fast-Path (<2ms In-Memory Scoring)"]
        L1Batch["Incoming L1 Ingress Batch\n(5,000 records)"]
        VectorScorer["VectorizedAnomalyScorer\n(NumPy / C-Accelerated Z-Score + MAD)"]
        ScoreEvaluator{"Score > 0.85?"}
        L3Outbox[("L3 Normalization Outbox\n(Clean Records)")]
        QuarantineTable[("PostgreSQL: ip_quarantine_hold\n(Quarantined Records)")]
    end

    subgraph OperationsTriage["Operations & Review Queue"]
        QuarantineUI["Quarantine Triage UI"]
        ReinjectAction["Re-Inject Approved Records to L3"]
    end

    L2ReplicaHistory --> BaselineTrainer
    BaselineTrainer --> RedisBaselineCache
    RedisBaselineCache -. "Sub-millisecond Read" .-> VectorScorer
    L1Batch --> VectorScorer
    VectorScorer --> ScoreEvaluator
    ScoreEvaluator -->|Clean (<= 0.85)| L3Outbox
    ScoreEvaluator -->|Anomalous (> 0.85)| QuarantineTable
    QuarantineTable --> QuarantineUI
    QuarantineUI --> ReinjectAction
    ReinjectAction --> L3Outbox
```

---

## 2. Open-Source Reference Architecture & Reused Foundations

Rather than hand-rolling raw statistical models and anomaly heuristics from scratch:
- **[PyOD](https://github.com/yzhao062/pyod) (Python Outlier Detection):** The comprehensive industry-standard Python library for detecting outliers in multivariate and time-series data. Informs our Modified Z-Score, Median Absolute Deviation (MAD), and lightweight Isolation Forest implementations.
- **[Alibi Detect](https://github.com/SeldonIO/alibi-detect) (Seldon):** Open-source library dedicated to outlier, adversarial, and drift detection. Powers our temporal gap and sequential flatline entropy algorithms.
- **[Evidently AI](https://github.com/evidentlyai/evidently):** Provides our baseline profile calculation engine, tracking rolling 14-day data drift, diurnal seasonal patterns, and feature distribution decay.
- **[NumPy](https://github.com/numpy/numpy) & C-Contiguous Array Vectorization:** Delivers sub-2ms inline scoring by executing pure vectorized SIMD operations over memory buffers without Python object boxing overhead.

---

## 3. Hexagonal Domain Model & DTO Contracts

```python
# apps/ip/packages/ip/src/ip/domain/models/stream_anomaly.py
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from seedwork.result import Result


class AnomalyType(StrEnum):
    FLATLINE_ZERO = "FLATLINE_ZERO"
    IMPOSSIBLE_SPIKE = "IMPOSSIBLE_SPIKE"
    TEMPORAL_GAP = "TEMPORAL_GAP"
    INVERTED_SIGN = "INVERTED_SIGN"
    UNSEASONAL_SHIFT = "UNSEASONAL_SHIFT"


class QuarantinePolicy(StrEnum):
    FLAG_AND_CONTINUE = "FLAG_AND_CONTINUE"
    QUARANTINE_HOLD = "QUARANTINE_HOLD"
    REJECT_IMMEDIATELY = "REJECT_IMMEDIATELY"


@dataclass(frozen=True, kw_only=True)
class AnomalyScoreResultDTO:
    record_id: str
    stream_id: str
    tenant_id: str
    is_anomalous: bool
    anomaly_score: float  # Range: 0.0 (Clean) to 1.0 (Definite Corruption)
    detected_type: AnomalyType | None
    observed_value: float | None
    expected_baseline_mean: float | None
    deviation_sigmas: float | None
    diagnostic_summary: str | None


@dataclass(frozen=True, kw_only=True)
class ClusterBaselineWeightsDTO:
    cluster_id: str
    rolling_mean: float
    rolling_std_dev: float
    median_absolute_deviation: float
    p01_lower_bound: float
    p99_upper_bound: float
    expected_cadence_seconds: int
    last_updated_at: str


class StreamAnomalyScorerPort(Protocol):
    def score_batch(
        self,
        records: list[dict[str, Any]],
        baseline: ClusterBaselineWeightsDTO,
    ) -> list[AnomalyScoreResultDTO]: ...


class BaselineStorePort(Protocol):
    async def get_baseline(
        self, cluster_id: str
    ) -> Result[ClusterBaselineWeightsDTO, str]: ...

    async def save_baseline(
        self, baseline: ClusterBaselineWeightsDTO
    ) -> Result[bool, str]: ...
```

---

## 3. Database Schema: Quarantine Queue & Anomaly Audit

```sql
-- Migration: 20261030_04_add_stream_anomaly_and_quarantine.sql

CREATE TABLE ip_quarantine_hold (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    stream_id VARCHAR(64) NOT NULL,
    record_id VARCHAR(128) NOT NULL,
    anomaly_type VARCHAR(32) NOT NULL,
    anomaly_score NUMERIC(4, 3) NOT NULL,
    raw_payload JSONB NOT NULL,
    observed_value NUMERIC(14, 4),
    expected_mean NUMERIC(14, 4),
    deviation_sigmas NUMERIC(8, 2),
    status VARCHAR(32) NOT NULL DEFAULT 'HELD', -- HELD, APPROVED, DISCARDED, ESTIMATED
    reviewed_by VARCHAR(64),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ip_quarantine_tenant_stream_status 
ON ip_quarantine_hold (tenant_id, stream_id, status, created_at DESC);

-- Chunked retention purging index
CREATE INDEX idx_ip_quarantine_retention 
ON ip_quarantine_hold (created_at);

ALTER TABLE ip_quarantine_hold ENABLE ROW LEVEL SECURITY;
ALTER TABLE ip_quarantine_hold FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_ip_quarantine ON ip_quarantine_hold
FOR ALL USING (tenant_id = current_setting('platform.current_tenant_id', true));
```

---

## 4. Vectorized Inline Scoring Algorithm Implementation

The inline scorer executes directly in Python using NumPy vectorization, achieving sub-2ms latency for 5,000-record batches:

```python
# apps/ip/packages/ip/src/ip/adapters/outbound/numpy_anomaly_scorer.py
import numpy as np
from ip.domain.models.stream_anomaly import (
    AnomalyScoreResultDTO,
    AnomalyType,
    ClusterBaselineWeightsDTO,
    StreamAnomalyScorerPort,
)


class VectorizedNumpyAnomalyScorer(StreamAnomalyScorerPort):
    def score_batch(
        self,
        records: list[dict[str, Any]],
        baseline: ClusterBaselineWeightsDTO,
    ) -> list[AnomalyScoreResultDTO]:
        if not records:
            return []

        # Extract numerical consumption values into a C-contiguous float array
        values = np.array(
            [r.get("reading_value", 0.0) for r in records], dtype=np.float64
        )

        # 1. Modified Z-Score using Median Absolute Deviation (MAD)
        mad = baseline.median_absolute_deviation
        if mad > 1e-6:
            modified_z_scores = (
                0.6745 * np.abs(values - baseline.rolling_mean) / mad
            )
        else:
            # Fallback to standard standard-deviation Z-score
            std = max(baseline.rolling_std_dev, 1e-6)
            modified_z_scores = np.abs(values - baseline.rolling_mean) / std

        # 2. Vectorized Flagging
        is_spike = (modified_z_scores > 4.5) & (
            values > baseline.p99_upper_bound
        )
        is_flatline = (np.abs(values) < 1e-6) & (baseline.rolling_mean > 0.5)
        is_negative = values < 0.0

        results: list[AnomalyScoreResultDTO] = []
        for idx, rec in enumerate(records):
            score = float(min(1.0, modified_z_scores[idx] / 5.0))
            detected_type = None

            if is_flatline[idx]:
                score = 0.95
                detected_type = AnomalyType.FLATLINE_ZERO
            elif is_spike[idx]:
                score = 0.99
                detected_type = AnomalyType.IMPOSSIBLE_SPIKE
            elif is_negative[idx]:
                score = 0.90
                detected_type = AnomalyType.INVERTED_SIGN

            is_anomalous = score > 0.85
            results.append(
                AnomalyScoreResultDTO(
                    record_id=str(rec.get("id", idx)),
                    stream_id=str(rec.get("stream_id", "default")),
                    tenant_id=str(rec.get("tenant_id", "default")),
                    is_anomalous=is_anomalous,
                    anomaly_score=round(score, 3),
                    detected_type=detected_type,
                    observed_value=float(values[idx]),
                    expected_baseline_mean=baseline.rolling_mean,
                    deviation_sigmas=float(round(modified_z_scores[idx], 2)),
                    diagnostic_summary=f"Deviation: {round(modified_z_scores[idx], 1)} sigma from cluster baseline"
                    if is_anomalous
                    else None,
                )
            )

        return results
```

---

## 5. Performance Benchmarks & SLAs

| Pipeline Step | Throughput / Latency Target | Implementation Mechanism |
| :--- | :--- | :--- |
| **Inline Batch Scoring (5,000 records)** | **$\le 1.8\text{ ms}$** | Vectorized NumPy C-buffer operations |
| **Baseline Weight Cache Fetch** | **$< 0.5\text{ ms}$** | Redis in-memory lookup (`MGET`) with local 5-min TTL |
| **Quarantine Diversion SQL Write** | **$< 15\text{ ms}$** | Keyset chunked `COPY` / multi-row batch insert |
| **Stream Processing Overhead** | **$< 1\%$ total latency** | Zero impact on downstream L3/L4 delivery |
