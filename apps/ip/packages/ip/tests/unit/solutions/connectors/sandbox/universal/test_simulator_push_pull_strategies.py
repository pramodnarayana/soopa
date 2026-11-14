"""Unit tests for the Universal Schema Simulator Push Cadence & Pull Extraction Strategies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from helpers.delivery_fakes import FakeControlPlaneUnitOfWork
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType
from ip.engine.domain.exceptions import IpErrorCode
from ip.solutions.connectors.sandbox.universal.cadence import (
    ChaosFaultCadenceStrategy,
    ConstantPacedCadenceStrategy,
    CronBatchCadenceStrategy,
    DiurnalWaveCadenceStrategy,
    ManualCadenceStrategy,
    PoissonJitterCadenceStrategy,
    RandomBurstCadenceStrategy,
    ThinPushCadenceStrategy,
    resolve_push_cadence_strategy,
)
from ip.solutions.connectors.sandbox.universal.connector import UniversalSchemaSimulatorConnector
from ip.solutions.connectors.sandbox.universal.dto import SimulatorEntityDTO
from ip.solutions.connectors.sandbox.universal.extraction import (
    BoundedTimeWindowExtractionStrategy,
    DeltaCdcExtractionStrategy,
    HighWatermarkExtractionStrategy,
    OffsetLimitExtractionStrategy,
    OpaqueTokenExtractionStrategy,
    PullQueryEngine,
    RateLimited429ExtractionStrategy,
)
from ip.solutions.connectors.sandbox.universal.inference import (
    parse_simulator_connection_config,
)
from ip.solutions.connectors.sandbox.universal.spec import (
    SimulatorStreamSpec,
    StreamVelocityMode,
)
from ip.solutions.connectors.sandbox.universal.strategies import (
    CadenceState,
    ExtractionQuery,
    PullExtractionMode,
    PushCadenceMode,
)
from ip.solutions.connectors.sandbox.universal.synthesizer import (
    EPOCH_ANCHOR,
    JsonSchemaRecordSynthesizer,
    _format_iso_utc,
)
from ip.solutions.connectors.sandbox.universal.use_cases.create_simulator_entity_use_case import (
    CreateSimulatorEntityCommand,
    CreateSimulatorEntityUseCase,
)
from ip.solutions.connectors.sandbox.universal.use_cases.pull_simulator_records_use_case import (
    PullSimulatorRecordsCommand,
    PullSimulatorRecordsUseCase,
)
from ip.solutions.connectors.sandbox.universal.use_cases.update_simulator_entity_use_case import (
    UpdateSimulatorEntityCommand,
    UpdateSimulatorEntityUseCase,
)
from unit.solutions.connectors.sandbox.universal.simulator_fakes import (
    FakeSimulatorUnitOfWork,
    InMemorySimulatorRepository,
)

# Generic Non-Meter E-Commerce Orders Schema
ORDER_STREAM_SPEC = SimulatorStreamSpec(
    stream_name="ecommerce_orders",
    primary_key_field="order_id",
    cursor_field="updated_at",
    records_per_pull=25,
    cursor_step_seconds=60,
    json_schema={
        "type": "object",
        "required": ["order_id", "customer_name", "total_amount", "currency", "status"],
        "properties": {
            "order_id": {"type": "string", "x_prefix": "ORD-", "x_digits": 6},
            "customer_name": {"type": "string", "x_semantic": "full_name"},
            "total_amount": {"type": "number", "minimum": 10.0, "maximum": 500.0},
            "currency": {"type": "string", "enum": ["USD", "EUR", "GBP"]},
            "status": {
                "type": "string",
                "enum": ["PENDING", "PROCESSING", "SHIPPED", "DELIVERED"],
            },
            "updated_at": {"type": "string", "format": "date-time"},
        },
    },
)


# ---------------------------------------------------------------------------
# 1. Push Cadence Strategy Tests
# ---------------------------------------------------------------------------


def test_constant_paced_cadence_computes_fixed_delay() -> None:
    strategy = ConstantPacedCadenceStrategy(messages_per_second=2.0)
    state = CadenceState(
        cycle_index=0,
        elapsed_seconds=0.0,
        total_emitted=0,
        last_emitted_at=datetime.now(tz=UTC),
    )

    assert strategy.compute_next_delay_seconds(state) == 0.5
    assert strategy.compute_batch_size(state) == 1
    assert strategy.should_emit(state) is True


def test_constant_paced_cadence_validates_positive_rate() -> None:
    strategy_zero = ConstantPacedCadenceStrategy(messages_per_second=0.0)
    assert strategy_zero.messages_per_second == 1.0

    strategy_negative = ConstantPacedCadenceStrategy(messages_per_second=-10.0)
    assert strategy_negative.messages_per_second == 1.0


def test_random_burst_cadence_varies_batch_size_within_bounds() -> None:
    strategy = RandomBurstCadenceStrategy(min_batch=2, max_batch=8, interval_seconds=3.0, seed=100)
    sizes: list[int] = []

    for i in range(10):
        state = CadenceState(
            cycle_index=i,
            elapsed_seconds=i * 3.0,
            total_emitted=sum(sizes),
            last_emitted_at=datetime.now(tz=UTC),
        )
        assert strategy.compute_next_delay_seconds(state) == 3.0
        assert strategy.should_emit(state) is True
        batch_size = strategy.compute_batch_size(state)
        assert 2 <= batch_size <= 8
        sizes.append(batch_size)

    # Verify that variation actually occurred across cycles
    assert len(set(sizes)) > 1


def test_poisson_jitter_cadence_varies_batch_delay_distribution() -> None:
    strategy = PoissonJitterCadenceStrategy(
        min_delay_seconds=0.5,
        max_delay_seconds=4.0,
        min_batch=1,
        max_batch=6,
        seed=200,
    )
    delays: list[float] = []

    for i in range(10):
        state = CadenceState(
            cycle_index=i,
            elapsed_seconds=sum(delays),
            total_emitted=i * 2,
            last_emitted_at=datetime.now(tz=UTC),
        )
        delay = strategy.compute_next_delay_seconds(state)
        batch = strategy.compute_batch_size(state)
        assert 0.5 <= delay <= 4.0
        assert 1 <= batch <= 6
        delays.append(delay)

    assert len(set(delays)) > 1


def test_diurnal_wave_cadence_modulates_by_hour() -> None:
    strategy = DiurnalWaveCadenceStrategy(
        base_rate_per_second=1.0,
        peak_multiplier=4.0,
        peak_hour_utc=14,
    )

    # 14:00 UTC = exact peak -> rate should be ~4.0 msg/s -> delay ~0.25s
    peak_time = datetime(2026, 3, 1, 14, 0, 0, tzinfo=UTC)
    state_peak = CadenceState(
        cycle_index=0, elapsed_seconds=0.0, total_emitted=0, last_emitted_at=peak_time
    )
    delay_peak = strategy.compute_next_delay_seconds(state_peak)

    # 02:00 UTC = exact trough -> rate should be ~1.0 msg/s -> delay ~1.0s
    trough_time = datetime(2026, 3, 1, 2, 0, 0, tzinfo=UTC)
    state_trough = CadenceState(
        cycle_index=1, elapsed_seconds=100.0, total_emitted=10, last_emitted_at=trough_time
    )
    delay_trough = strategy.compute_next_delay_seconds(state_trough)

    assert delay_peak < delay_trough
    assert pytest.approx(delay_peak, rel=0.1) == 0.25
    assert pytest.approx(delay_trough, rel=0.1) == 1.0


def test_cron_batch_cadence_emits_macro_batch() -> None:
    strategy = CronBatchCadenceStrategy(interval_seconds=1800.0, batch_size=250)
    state = CadenceState(
        cycle_index=0,
        elapsed_seconds=0.0,
        total_emitted=0,
        last_emitted_at=datetime.now(tz=UTC),
    )

    assert strategy.compute_next_delay_seconds(state) == 1800.0
    assert strategy.compute_batch_size(state) == 250
    assert strategy.should_emit(state) is True


def test_thin_push_cadence_emits_single_ping() -> None:
    strategy = ThinPushCadenceStrategy(interval_seconds=1.5)
    state = CadenceState(
        cycle_index=0,
        elapsed_seconds=0.0,
        total_emitted=0,
        last_emitted_at=datetime.now(tz=UTC),
    )

    assert strategy.compute_next_delay_seconds(state) == 1.5
    assert strategy.compute_batch_size(state) == 1


def test_chaos_fault_cadence_injects_jittered_drop_faults() -> None:
    strategy = ChaosFaultCadenceStrategy(
        base_interval_seconds=1.0,
        batch_size=10,
        drop_rate_percent=50.0,
        seed=42,
    )
    should_emit_results: list[bool] = []

    for i in range(20):
        state = CadenceState(
            cycle_index=i,
            elapsed_seconds=float(i),
            total_emitted=i * 10,
            last_emitted_at=datetime.now(tz=UTC),
        )
        delay = strategy.compute_next_delay_seconds(state)
        assert delay >= 1.0
        should_emit_results.append(strategy.should_emit(state))

    # With a 50% drop rate across 20 cycles, there should be both True and False outcomes
    assert True in should_emit_results
    assert False in should_emit_results


def test_resolve_push_cadence_strategy_factory() -> None:
    s_manual = resolve_push_cadence_strategy(PushCadenceMode.MANUAL, {"records_per_push": 7})
    assert isinstance(s_manual, ManualCadenceStrategy)
    assert s_manual.records_per_push == 7

    s_paced = resolve_push_cadence_strategy(
        PushCadenceMode.CONSTANT_PACED, {"messages_per_second": 5.0}
    )
    assert isinstance(s_paced, ConstantPacedCadenceStrategy)
    assert s_paced.messages_per_second == 5.0

    s_burst = resolve_push_cadence_strategy(
        PushCadenceMode.RANDOM_BURST, {"min_batch": 3, "max_batch": 9}
    )
    assert isinstance(s_burst, RandomBurstCadenceStrategy)
    assert s_burst.min_batch == 3
    assert s_burst.max_batch == 9

    s_jitter = resolve_push_cadence_strategy(
        PushCadenceMode.POISSON_JITTER, {"min_delay_seconds": 2.0}
    )
    assert isinstance(s_jitter, PoissonJitterCadenceStrategy)

    s_diurnal = resolve_push_cadence_strategy(
        PushCadenceMode.DIURNAL_WAVE, {"peak_multiplier": 8.0}
    )
    assert isinstance(s_diurnal, DiurnalWaveCadenceStrategy)

    s_cron = resolve_push_cadence_strategy(PushCadenceMode.CRON_BATCH, {"batch_size": 1000})
    assert isinstance(s_cron, CronBatchCadenceStrategy)

    s_thin = resolve_push_cadence_strategy(PushCadenceMode.THIN_PUSH)
    assert isinstance(s_thin, ThinPushCadenceStrategy)

    s_chaos = resolve_push_cadence_strategy(
        PushCadenceMode.CHAOS_FAULT, {"drop_rate_percent": 35.0}
    )
    assert isinstance(s_chaos, ChaosFaultCadenceStrategy)


# ---------------------------------------------------------------------------
# 2. Pull Extraction Strategy Tests
# ---------------------------------------------------------------------------


def test_bounded_time_window_extracts_temporal_slice_pages() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    strategy = BoundedTimeWindowExtractionStrategy(synthesizer)

    # 1-hour window with 60-second steps = 60 records
    start_dt = EPOCH_ANCHOR + timedelta(hours=2)
    end_dt = start_dt + timedelta(hours=1)

    # Page 1: limit 25
    q1 = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.BOUNDED_TIME_WINDOW,
        start_time=start_dt,
        end_time=end_dt,
        limit=25,
    )
    res1 = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q1)
    assert res1.is_ok
    slice1 = res1.unwrap()
    assert len(slice1.records) == 25
    assert slice1.has_more is True
    assert slice1.next_offset is not None
    assert slice1.total_estimated == 61  # closed interval count

    # Verify order schema fields
    first_record = slice1.records[0]
    assert first_record.record_id.startswith("ORD-")
    assert "customer_name" in first_record.data
    assert "total_amount" in first_record.data
    assert first_record.data["currency"] in ("USD", "EUR", "GBP")

    # Page 2: continue from next_offset
    q2 = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.BOUNDED_TIME_WINDOW,
        start_time=start_dt,
        end_time=end_dt,
        offset=slice1.next_offset,
        limit=25,
    )
    res2 = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q2)
    assert res2.is_ok
    slice2 = res2.unwrap()
    assert len(slice2.records) == 25
    assert slice2.has_more is True

    # Page 3: last 11 records
    q3 = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.BOUNDED_TIME_WINDOW,
        start_time=start_dt,
        end_time=end_dt,
        offset=slice2.next_offset,
        limit=25,
    )
    res3 = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q3)
    assert res3.is_ok
    slice3 = res3.unwrap()
    assert len(slice3.records) == 11
    assert slice3.has_more is False
    assert slice3.next_offset is None
    assert slice3.next_cursor is None

    # Total records extracted across 3 pages
    total_records = len(slice1.records) + len(slice2.records) + len(slice3.records)
    assert total_records == 61

    # Verify record IDs across pages are strictly sequential and unique
    all_ids = (
        [r.record_id for r in slice1.records]
        + [r.record_id for r in slice2.records]
        + [r.record_id for r in slice3.records]
    )
    assert len(set(all_ids)) == 61


def test_bounded_time_window_rejects_invalid_chronology() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    strategy = BoundedTimeWindowExtractionStrategy(synthesizer)

    start_dt = EPOCH_ANCHOR + timedelta(hours=5)
    end_dt = EPOCH_ANCHOR + timedelta(hours=2)

    q = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.BOUNDED_TIME_WINDOW,
        start_time=start_dt,
        end_time=end_dt,
    )
    res = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q)
    assert res.is_err
    assert res.unwrap_err().code == IpErrorCode.VALIDATION_FAILED
    assert res.unwrap_err().http_status == 400


def test_high_watermark_strategy_increments_cursor() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    strategy = HighWatermarkExtractionStrategy(synthesizer)

    cursor_0 = _format_iso_utc(EPOCH_ANCHOR)
    q1 = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.HIGH_WATERMARK,
        cursor=cursor_0,
        limit=10,
    )
    res1 = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q1)
    assert res1.is_ok
    slice1 = res1.unwrap()
    assert len(slice1.records) == 10
    assert slice1.next_cursor is not None
    assert slice1.next_cursor > cursor_0

    # Query next batch using advanced cursor
    q2 = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.HIGH_WATERMARK,
        cursor=slice1.next_cursor,
        limit=10,
    )
    res2 = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q2)
    assert res2.is_ok
    slice2 = res2.unwrap()
    assert len(slice2.records) == 10
    assert slice2.records[0].cursor_value is not None
    assert slice1.next_cursor is not None
    assert slice2.records[0].cursor_value > slice1.next_cursor


def test_offset_limit_strategy_paginates_sequentially() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    strategy = OffsetLimitExtractionStrategy(synthesizer)

    q1 = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.OFFSET_LIMIT,
        offset=0,
        limit=5,
    )
    res1 = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q1)
    assert res1.is_ok
    slice1 = res1.unwrap()
    assert len(slice1.records) == 5
    assert slice1.next_offset == 5

    q2 = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.OFFSET_LIMIT,
        offset=slice1.next_offset,
        limit=5,
    )
    res2 = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q2)
    assert res2.is_ok
    slice2 = res2.unwrap()
    assert len(slice2.records) == 5
    assert slice2.next_offset == 10

    # Check that sequential record IDs don't overlap
    set1 = {r.record_id for r in slice1.records}
    set2 = {r.record_id for r in slice2.records}
    assert len(set1.intersection(set2)) == 0


def test_opaque_token_strategy_round_trips_tokens() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    strategy = OpaqueTokenExtractionStrategy(synthesizer)

    q1 = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.OPAQUE_TOKEN,
        limit=5,
    )
    res1 = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q1)
    assert res1.is_ok
    slice1 = res1.unwrap()
    assert slice1.continuation_token is not None

    # Use token for page 2
    q2 = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.OPAQUE_TOKEN,
        token=slice1.continuation_token,
        limit=5,
    )
    res2 = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q2)
    assert res2.is_ok
    slice2 = res2.unwrap()
    assert len(slice2.records) == 5
    assert slice2.continuation_token is not None
    assert slice2.continuation_token != slice1.continuation_token

    # Invalid token rejected
    bad_q = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.OPAQUE_TOKEN,
        token="not-valid-base64!!!",
    )
    bad_res = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=bad_q)
    assert bad_res.is_err
    assert bad_res.unwrap_err().code == IpErrorCode.VALIDATION_FAILED


def test_delta_cdc_strategy_decorates_operations() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    strategy = DeltaCdcExtractionStrategy(synthesizer)

    q = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.DELTA_CDC,
        since_version=10,
        limit=6,
    )
    res = strategy.extract(ORDER_STREAM_SPEC, seed=42, query=q)
    assert res.is_ok
    slice_dto = res.unwrap()
    assert len(slice_dto.records) == 6

    # Verify CDC operational attributes
    for r in slice_dto.records:
        assert "_cdc_op" in r.data
        assert r.data["_cdc_op"] in ("INSERT", "UPDATE")
        assert "_cdc_version" in r.data
        cdc_v = r.data["_cdc_version"]
        assert isinstance(cdc_v, (int, str))
        assert int(cdc_v) > 10


def test_rate_limited_429_strategy_throttles_excessive_polls() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    base_strategy = HighWatermarkExtractionStrategy(synthesizer)
    throttled = RateLimited429ExtractionStrategy(
        base_strategy, max_requests_per_window=3, window_seconds=2.0
    )

    q = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.RATE_LIMITED_429,
        limit=5,
    )

    # First 3 calls succeed
    for _ in range(3):
        res = throttled.extract(ORDER_STREAM_SPEC, seed=42, query=q)
        assert res.is_ok

    # 4th call immediately triggers 429
    res_blocked = throttled.extract(ORDER_STREAM_SPEC, seed=42, query=q)
    assert res_blocked.is_err
    err = res_blocked.unwrap_err()
    assert err.code == IpErrorCode.RATE_LIMIT_EXCEEDED
    assert err.http_status == 429
    assert "retry_after_seconds" in err.details


def test_rate_limited_429_strategy_evicts_stale_history() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    base_strategy = HighWatermarkExtractionStrategy(synthesizer)
    throttled = RateLimited429ExtractionStrategy(
        base_strategy, max_requests_per_window=3, window_seconds=2.0
    )
    key = f"{ORDER_STREAM_SPEC.stream_name}_99"
    # Seed stale timestamps outside 2.0s window
    throttled._client_history[key] = [0.1, 0.2, 0.3]

    q = ExtractionQuery(
        stream_name=ORDER_STREAM_SPEC.stream_name,
        mode=PullExtractionMode.RATE_LIMITED_429,
        limit=5,
    )
    res = throttled.extract(ORDER_STREAM_SPEC, seed=99, query=q)
    assert res.is_ok
    # Stale timestamps pruned, only current call retained
    assert len(throttled._client_history[key]) == 1


def test_pull_query_engine_dispatches_cleanly() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    engine = PullQueryEngine(synthesizer)

    # Bounded query
    q_bounded = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.BOUNDED_TIME_WINDOW,
        start_time=EPOCH_ANCHOR,
        end_time=EPOCH_ANCHOR + timedelta(minutes=10),
        limit=5,
    )
    assert engine.execute(ORDER_STREAM_SPEC, seed=42, query=q_bounded).is_ok

    # Watermark query
    q_watermark = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.HIGH_WATERMARK,
        limit=5,
    )
    assert engine.execute(ORDER_STREAM_SPEC, seed=42, query=q_watermark).is_ok

    # Offset query
    q_offset = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.OFFSET_LIMIT,
        offset=10,
        limit=5,
    )
    assert engine.execute(ORDER_STREAM_SPEC, seed=42, query=q_offset).is_ok


# ---------------------------------------------------------------------------
# 3. Pull Simulator Records Use Case Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_simulator_records_use_case_e2e() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    connections = cp_uow.connections
    entities = InMemorySimulatorRepository()

    # Seed Connection
    conn = Connection.create(
        tenant_id="tnt_retail",
        app_id=UniversalSchemaSimulatorConnector.APP_ID,
        name="Retail Orders Simulator",
        auth_type=AuthType.NO_AUTH,
        public_config={"seed": 77, "records_per_pull": 25},
        encrypted_credentials=b"",
        endpoint_for_fingerprint="Retail Orders Simulator",
    )
    conn.activate()
    await connections.save(conn)

    # Seed Entity for generic E-Commerce Orders
    entity = SimulatorEntityDTO(
        id="sim_ent_orders",
        tenant_id="tnt_retail",
        connection_id=conn.id,
        entity_name="ecommerce_orders",
        primary_key_field="order_id",
        cursor_field="updated_at",
        records_per_pull=25,
        cursor_step_seconds=60,
        velocity_mode=StreamVelocityMode.ENTITY_TRANSACTIONAL,
        sample_blueprint={},
        inferred_json_schema=dict(ORDER_STREAM_SPEC.json_schema),
        chaos_policy={},
        version=1,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    await entities.create_entity(entity)

    use_case = PullSimulatorRecordsUseCase(
        cp_uow=cp_uow,
        entity_reader=entities,
    )

    # Execute Bounded Query
    start_dt = EPOCH_ANCHOR + timedelta(hours=1)
    end_dt = start_dt + timedelta(minutes=30)
    cmd = PullSimulatorRecordsCommand(
        tenant_id="tnt_retail",
        connection_id=conn.id,
        stream_name="ecommerce_orders",
        query=ExtractionQuery(
            stream_name="ecommerce_orders",
            mode=PullExtractionMode.BOUNDED_TIME_WINDOW,
            start_time=start_dt,
            end_time=end_dt,
            limit=15,
        ),
    )

    res = await use_case.execute(cmd)
    assert res.is_ok
    slice_dto = res.unwrap()
    assert len(slice_dto.records) == 15
    assert slice_dto.has_more is True
    assert slice_dto.records[0].record_id.startswith("ORD-")

    # Rejection when stream does not exist
    bad_cmd = PullSimulatorRecordsCommand(
        tenant_id="tnt_retail",
        connection_id=conn.id,
        stream_name="non_existent_stream",
        query=ExtractionQuery(
            stream_name="non_existent_stream",
            mode=PullExtractionMode.HIGH_WATERMARK,
        ),
    )
    bad_res = await use_case.execute(bad_cmd)
    assert bad_res.is_err
    assert bad_res.unwrap_err().code == IpErrorCode.STREAM_NOT_FOUND


# ---------------------------------------------------------------------------
# 4. Connector query_slice Integration Test
# ---------------------------------------------------------------------------


def test_connector_query_slice_integration() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    connector = UniversalSchemaSimulatorConnector(synthesizer=synthesizer)

    query = ExtractionQuery(
        stream_name="ecommerce_orders",
        mode=PullExtractionMode.OFFSET_LIMIT,
        offset=50,
        limit=10,
    )
    res = connector.query_slice(ORDER_STREAM_SPEC, seed=99, query=query)
    assert res.is_ok
    slice_dto = res.unwrap()
    assert len(slice_dto.records) == 10
    assert slice_dto.records[0].record_id == "ORD-000051"


# ---------------------------------------------------------------------------
# 5. Connection Zero-Config & Entity Push Mode Tests
# ---------------------------------------------------------------------------


def test_connection_auto_derives_seed_from_connection_id_when_missing() -> None:
    """Non-tech user leaves connection zero-config; seed is deterministically auto-derived."""
    cfg1 = parse_simulator_connection_config({}, connection_id="conn-alpha-12345")
    cfg2 = parse_simulator_connection_config({}, connection_id="conn-alpha-12345")
    cfg3 = parse_simulator_connection_config({}, connection_id="conn-beta-67890")

    assert cfg1.seed != 42
    assert cfg1.seed == cfg2.seed
    assert cfg1.seed != cfg3.seed
    assert cfg1.default_records_per_pull == 25


def test_connector_spec_exposes_no_technical_properties() -> None:
    """Simulator connector spec has zero technical properties for non-tech users."""
    connector = UniversalSchemaSimulatorConnector()
    app_spec = connector.spec()
    assert app_spec.properties == ()
    assert app_spec.auth_type == AuthType.NO_AUTH


async def test_entity_push_mode_config_lifecycle() -> None:
    """Simulator entity requires only push cadence configuration and validates invariants."""
    repo = InMemorySimulatorRepository()
    uow = FakeSimulatorUnitOfWork(repo)
    cp_uow = FakeControlPlaneUnitOfWork()

    conn = Connection.create(
        tenant_id="tnt_push",
        app_id=UniversalSchemaSimulatorConnector.APP_ID,
        name="Push Simulator",
        auth_type=AuthType.NO_AUTH,
        public_config={},
        encrypted_credentials=b"",
        endpoint_for_fingerprint="Push Simulator",
    )
    conn.activate()
    await cp_uow.connections.save(conn)

    create_uc = CreateSimulatorEntityUseCase(uow=uow, connections=cp_uow.connections)
    update_uc = UpdateSimulatorEntityUseCase(uow=uow, connections=cp_uow.connections)

    # 1. Reject invalid push_config (e.g. non-positive messages_per_second)
    bad_res = await create_uc.execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_push",
            connection_id=conn.id,
            entity_name="events",
            sample_blueprint={"event_id": "EVT-1", "ts": "2026-05-01T00:00:00Z"},
            push_mode=PushCadenceMode.CONSTANT_PACED,
            push_config={"messages_per_second": -5.0},
        )
    )
    assert bad_res.is_err
    assert bad_res.unwrap_err().code == IpErrorCode.INVALID_CONFIG

    # 2. Successfully create entity with valid push_mode and push_config
    create_res = await create_uc.execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_push",
            connection_id=conn.id,
            entity_name="events",
            sample_blueprint={"event_id": "EVT-1", "ts": "2026-05-01T00:00:00Z"},
            push_mode=PushCadenceMode.CONSTANT_PACED,
            push_config={"messages_per_second": 10.0},
        )
    )
    assert create_res.is_ok
    created = create_res.unwrap()
    assert created.push_mode == PushCadenceMode.CONSTANT_PACED
    assert created.push_config == {"messages_per_second": 10.0}

    # 3. Update entity push_mode to CRON_BATCH with valid cron expression
    update_res = await update_uc.execute(
        UpdateSimulatorEntityCommand(
            tenant_id="tnt_push",
            connection_id=conn.id,
            entity_id=created.id,
            push_mode=PushCadenceMode.CRON_BATCH,
            push_config={"cron_expression": "*/15 * * * *", "batch_size": 50},
        )
    )
    assert update_res.is_ok
    updated = update_res.unwrap()
    assert updated.push_mode == PushCadenceMode.CRON_BATCH
    assert updated.push_config["cron_expression"] == "*/15 * * * *"
    assert updated.push_config["batch_size"] == 50

    # 4. Reject invalid cron expression during update
    bad_update = await update_uc.execute(
        UpdateSimulatorEntityCommand(
            tenant_id="tnt_push",
            connection_id=conn.id,
            entity_id=created.id,
            push_config={"cron_expression": "not_a_cron_expression"},
        )
    )
    assert bad_update.is_err
    assert bad_update.unwrap_err().code == IpErrorCode.INVALID_CONFIG


async def test_read_stream_honours_caller_pull_limit() -> None:
    """Pull query limit is specified by Soopa IP sync / pull request, not clamped to entity default."""
    repo = InMemorySimulatorRepository()
    cp_uow = FakeControlPlaneUnitOfWork()

    conn = Connection.create(
        tenant_id="tnt_pull",
        app_id=UniversalSchemaSimulatorConnector.APP_ID,
        name="Pull Simulator",
        auth_type=AuthType.NO_AUTH,
        public_config={},
        encrypted_credentials=b"",
        endpoint_for_fingerprint="Pull Simulator",
    )
    conn.activate()
    await cp_uow.connections.save(conn)

    entity = SimulatorEntityDTO(
        id="sim_ent_telemetry",
        tenant_id="tnt_pull",
        connection_id=conn.id,
        entity_name="telemetry",
        primary_key_field="order_id",
        cursor_field="updated_at",
        records_per_pull=25,
        cursor_step_seconds=60,
        velocity_mode=StreamVelocityMode.ENTITY_TRANSACTIONAL,
        sample_blueprint={},
        inferred_json_schema=dict(ORDER_STREAM_SPEC.json_schema),
        chaos_policy={},
        version=1,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    await repo.create_entity(entity)

    connector = UniversalSchemaSimulatorConnector(entity_reader=repo)

    # Ingestion pipeline requests 60 records; connector must fulfill up to 60, not clamp to 25
    pulled = [
        rec
        async for rec in connector.read_stream(
            stream_name="telemetry",
            public_config={},
            credentials={},
            limit=60,
            tenant_id="tnt_pull",
            connection_id=conn.id,
        )
    ]
    assert len(pulled) == 60
    assert pulled[0].record_id.startswith("ORD-")
