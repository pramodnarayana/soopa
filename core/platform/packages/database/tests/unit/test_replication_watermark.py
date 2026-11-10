from __future__ import annotations

import pytest

from database.replication_watermark import (
    format_postgres_lsn,
    max_watermark,
    parse_postgres_lsn,
)
from database.types import ReplicationWatermark


def test_parse_postgres_lsn_roundtrip() -> None:
    wm_zero = parse_postgres_lsn("0/0")
    wm_low = parse_postgres_lsn("0/16B3748")
    wm_high = parse_postgres_lsn("16/B374D848")

    assert wm_zero == ReplicationWatermark(0)
    assert wm_zero < wm_low < wm_high
    assert format_postgres_lsn(wm_zero) == "0/0"
    assert format_postgres_lsn(wm_low) == "0/16B3748"
    assert format_postgres_lsn(wm_high) == "16/B374D848"
    assert max_watermark(wm_low, wm_high) == wm_high
    assert max_watermark(wm_high, wm_low) == wm_high


@pytest.mark.parametrize(
    "invalid_lsn",
    [
        "",
        "16B3748",
        "16/B374/00",
        "ZZ/10",
        "0/FFFFFFFF0",
        "-1/0",
    ],
)
def test_parse_postgres_lsn_rejects_malformed_inputs(invalid_lsn: str) -> None:
    with pytest.raises(ValueError, match="Invalid replication watermark LSN"):
        parse_postgres_lsn(invalid_lsn)


def test_format_postgres_lsn_rejects_out_of_bounds_values() -> None:
    with pytest.raises(ValueError, match="out of 64-bit unsigned range"):
        format_postgres_lsn(ReplicationWatermark(-1))
