"""Columnar Interval Outbound Adapters."""

from ip.engine.adapters.outbound.intervals.columnar_batch_codec import (
    ARROW_IPC_STREAM_MAGIC,
    decode_arrow_ipc_stream,
    encode_arrow_ipc_stream,
)
from ip.engine.adapters.outbound.intervals.interval_batch_normalizer import (
    VectorizedIntervalBatchNormalizerAdapter,
)
from ip.engine.adapters.outbound.intervals.interval_rollup_repository import (
    COLUMNAR_DAILY_COMPLETENESS_MV_DDL,
    COLUMNAR_HOURLY_ROLLUPS_MV_DDL,
    COLUMNAR_INTERVAL_READINGS_DDL,
    COLUMNAR_ROW_POLICY_DDL,
    ColumnarArrowDriverPort,
    ColumnarIntervalRollupRepositoryAdapter,
)

__all__ = [
    "ARROW_IPC_STREAM_MAGIC",
    "COLUMNAR_DAILY_COMPLETENESS_MV_DDL",
    "COLUMNAR_HOURLY_ROLLUPS_MV_DDL",
    "COLUMNAR_INTERVAL_READINGS_DDL",
    "COLUMNAR_ROW_POLICY_DDL",
    "ColumnarArrowDriverPort",
    "ColumnarIntervalRollupRepositoryAdapter",
    "VectorizedIntervalBatchNormalizerAdapter",
    "decode_arrow_ipc_stream",
    "encode_arrow_ipc_stream",
]
