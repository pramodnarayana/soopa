"""Stitch workflow execution enumerations."""

from enum import StrEnum


class StitchStepType(StrEnum):
    """Enterprise constant step_type identifiers for built-in IP Stitch handlers."""

    QUERY_REPLICA = "ip.stitch.query_replica"
    EXECUTE_HTTP_ACTION = "ip.stitch.execute_http_action"
    EMIT_NOTIFICATION = "ip.stitch.emit_notification"
