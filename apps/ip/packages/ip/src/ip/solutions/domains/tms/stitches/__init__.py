"""TMS domain L4 Stitch workflow definitions and stitch instances."""

from __future__ import annotations

from orchestration.domain.definition import WorkflowDefinition

from ip.engine.domain.stitch.stitch import Stitch
from ip.solutions.domains.tms.stitches.load_tender_erp_sync import (
    build_load_tender_erp_sync_definition,
    build_load_tender_erp_sync_stitch,
)


def build_tms_stitch_definitions() -> tuple[WorkflowDefinition, ...]:
    """Return all built-in WorkflowDefinitions owned by the TMS bounded context."""
    return (build_load_tender_erp_sync_definition(),)


def build_tms_stitches() -> tuple[Stitch, ...]:
    """Return all built-in Stitch instances owned by the TMS bounded context."""
    return (build_load_tender_erp_sync_stitch(),)


__all__ = [
    "build_load_tender_erp_sync_definition",
    "build_load_tender_erp_sync_stitch",
    "build_tms_stitch_definitions",
    "build_tms_stitches",
]
