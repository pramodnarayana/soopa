"""Unit tests for Energy and TMS domain L4 Stitch definitions and registry assembly."""

from __future__ import annotations

from ip.engine.adapters.outbound.stitches.stitch_catalog_registry import (
    InMemoryStitchCatalogRegistry,
)
from ip.engine.domain.stitch.stitch import Stitch
from ip.solutions.domains.energy.canonical import EnergyEntityType
from ip.solutions.domains.energy.stitches import (
    build_energy_stitch_definitions,
    build_energy_stitches,
    build_hes_historical_extraction_definition,
    build_hes_historical_extraction_stitch,
    build_meter_reading_erp_sync_definition,
    build_meter_reading_erp_sync_stitch,
    build_outage_restoration_definition,
)
from ip.solutions.domains.tms.canonical import TmsEntityType
from ip.solutions.domains.tms.stitches import (
    build_load_tender_erp_sync_definition,
    build_load_tender_erp_sync_stitch,
    build_tms_stitch_definitions,
    build_tms_stitches,
)
from ip.solutions.registry_loader import (
    build_default_stitch_definitions,
    build_default_stitches,
    create_default_workflow_definition_registry,
    register_default_stitches,
)
from orchestration.application.services import InMemoryWorkflowDefinitionRegistry
from orchestration.domain.constants import Priority


def test_energy_domain_stitch_definitions_with_instances() -> None:
    """Verify Energy domain builds expected DAG definitions and trigger stitches."""
    definitions = build_energy_stitch_definitions()
    assert len(definitions) == 3

    workflow_ids = {d.workflow_id for d in definitions}
    assert workflow_ids == {
        "energy.outage_restoration_stitch",
        "energy.meter_reading_erp_sync_stitch",
        "energy.hes_historical_extraction_stitch",
    }

    outage = build_outage_restoration_definition()
    assert outage.workflow_id == "energy.outage_restoration_stitch"
    assert outage.default_priority == Priority.REALTIME
    assert len(outage.nodes) == 3

    reading_sync_def = build_meter_reading_erp_sync_definition()
    assert reading_sync_def.workflow_id == "energy.meter_reading_erp_sync_stitch"
    assert reading_sync_def.default_priority == Priority.BULK
    assert len(reading_sync_def.nodes) == 2

    reading_stitch = build_meter_reading_erp_sync_stitch()
    assert isinstance(reading_stitch, Stitch)
    assert reading_stitch.workflow_id == "energy.meter_reading_erp_sync_stitch"
    assert reading_stitch.canonical_event_type == EnergyEntityType.MDM_METER_READING.value
    assert reading_stitch.is_trigger is True
    assert reading_stitch.idempotency_key_field == "event_id"
    assert reading_stitch.concurrency_key_field == "meter_serial_number"
    assert reading_stitch.is_active is False

    hes_def = build_hes_historical_extraction_definition()
    assert hes_def.workflow_id == "energy.hes_historical_extraction_stitch"
    assert hes_def.default_priority == Priority.BULK

    hes_stitch = build_hes_historical_extraction_stitch()
    assert hes_stitch.workflow_id == "energy.hes_historical_extraction_stitch"
    assert hes_stitch.canonical_event_type == "command.historical_extract_requests"
    assert hes_stitch.idempotency_key_field == "source_inbound_record_id"
    assert hes_stitch.is_active is False

    energy_stitches = build_energy_stitches()
    assert len(energy_stitches) == 2


def test_tms_domain_stitch_definitions_with_instances() -> None:
    """Verify TMS domain builds expected DAG definitions and trigger stitches."""
    definitions = build_tms_stitch_definitions()
    assert len(definitions) == 1

    tms_def = build_load_tender_erp_sync_definition()
    assert tms_def.workflow_id == "tms.load_tender_erp_sync_stitch"
    assert tms_def.default_priority == Priority.REALTIME
    assert len(tms_def.nodes) == 3

    tms_stitch = build_load_tender_erp_sync_stitch()
    assert isinstance(tms_stitch, Stitch)
    assert tms_stitch.workflow_id == "tms.load_tender_erp_sync_stitch"
    assert tms_stitch.canonical_event_type == TmsEntityType.TMS_LOAD.value
    assert tms_stitch.is_trigger is True
    assert tms_stitch.idempotency_key_field == "event_id"
    assert tms_stitch.concurrency_key_field == "load_reference_number"
    assert tms_stitch.is_active is False

    tms_stitches = build_tms_stitches()
    assert len(tms_stitches) == 1


def test_central_stitch_registry_loader_aggregates_bounded_contexts() -> None:
    """Verify the IoC registry loader aggregates all domains and registers them properly."""
    all_definitions = build_default_stitch_definitions()
    assert len(all_definitions) == 4
    all_ids = {d.workflow_id for d in all_definitions}
    assert all_ids == {
        "energy.outage_restoration_stitch",
        "energy.meter_reading_erp_sync_stitch",
        "energy.hes_historical_extraction_stitch",
        "tms.load_tender_erp_sync_stitch",
    }

    all_stitches = build_default_stitches()
    assert len(all_stitches) == 3
    stitch_workflows = {s.workflow_id for s in all_stitches}
    assert stitch_workflows == {
        "energy.meter_reading_erp_sync_stitch",
        "energy.hes_historical_extraction_stitch",
        "tms.load_tender_erp_sync_stitch",
    }

    workflow_registry = create_default_workflow_definition_registry()
    assert isinstance(workflow_registry, InMemoryWorkflowDefinitionRegistry)
    for wf_id in all_ids:
        assert workflow_registry.get(wf_id, 1) is not None

    stitch_registry = InMemoryStitchCatalogRegistry()
    register_default_stitches(stitch_registry)
    all_registered = stitch_registry.list_stitches(tenant_id="tenant_alpha")
    assert len(all_registered) == 3
    for stitch in all_stitches:
        assert any(s.workflow_id == stitch.workflow_id for s in all_registered)
        # Built-in template stitches are inactive by default to avoid unsolicited trigger runs
        active_matches = stitch_registry.list_stitches_for_event(
            tenant_id="tenant_alpha",
            canonical_event_type=stitch.canonical_event_type,
        )
        assert len(active_matches) == 0
