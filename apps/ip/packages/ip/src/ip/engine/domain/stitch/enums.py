"""Stitch workflow execution enumerations."""

from enum import StrEnum


class StitchStepType(StrEnum):
    """Enterprise constant step_type identifiers for built-in IP Stitch handlers."""

    QUERY_REPLICA = "ip.stitch.query_replica"
    EXECUTE_HTTP_ACTION = "ip.stitch.execute_http_action"
    EMIT_NOTIFICATION = "ip.stitch.emit_notification"
    SLICE_RANGE = "ip.stitch.slice_range"
    HTTP_DISPATCH = "ip.stitch.http_dispatch"
    L1_PERSIST = "ip.stitch.l1_persist"
    L2_REPLICA = "ip.stitch.l2_replica"
    NORMALIZER = "ip.stitch.normalizer"
    UI_FIELD_MAPPER = "ip.stitch.ui_field_mapper"
    EGRESS_PUBLISH = "ip.stitch.egress_publish"
