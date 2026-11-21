"""Energy domain historical backfill stitches."""

from __future__ import annotations

from ip.solutions.domains.energy.stitches.backfill.hes1_file_backfill_stitch import (
    HES1_FILE_BACKFILL_STITCH,
    execute_hes1_file_backfill_request,
    transform_hes1_file_reading,
)
from ip.solutions.domains.energy.stitches.backfill.hes2_kafka_backfill_stitch import (
    HES2_KAFKA_BACKFILL_STITCH,
    drain_hes2_kafka_stream,
    transform_hes2_kafka_reading,
)
from ip.solutions.domains.energy.stitches.backfill.itron_backfill_stitch import (
    ITRON_METER_READINGS_BACKFILL_STITCH,
)
from ip.solutions.domains.energy.stitches.backfill.landis_backfill_stitch import (
    LANDIS_METER_READINGS_BACKFILL_STITCH,
)
from ip.solutions.domains.energy.stitches.backfill.multi_hes_backfill_stitch import (
    MULTI_HES_BACKFILL_STITCH,
    HesBackfillCommand,
    HesBackfillResult,
    HesDispatchedJob,
    execute_multi_hes_backfill,
    resolve_hes_fetcher,
    resolve_hes_normalizer,
)
from ip.solutions.domains.energy.stitches.backfill.siemens_backfill_stitch import (
    SIEMENS_METER_READINGS_BACKFILL_STITCH,
)

__all__ = [
    "HES1_FILE_BACKFILL_STITCH",
    "HES2_KAFKA_BACKFILL_STITCH",
    "ITRON_METER_READINGS_BACKFILL_STITCH",
    "LANDIS_METER_READINGS_BACKFILL_STITCH",
    "MULTI_HES_BACKFILL_STITCH",
    "SIEMENS_METER_READINGS_BACKFILL_STITCH",
    "HesBackfillCommand",
    "HesBackfillResult",
    "HesDispatchedJob",
    "drain_hes2_kafka_stream",
    "execute_hes1_file_backfill_request",
    "execute_multi_hes_backfill",
    "resolve_hes_fetcher",
    "resolve_hes_normalizer",
    "transform_hes1_file_reading",
    "transform_hes2_kafka_reading",
]
