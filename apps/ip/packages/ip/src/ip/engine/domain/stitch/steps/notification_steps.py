"""Strongly-typed DTOs for EmitNotification Stitch steps."""

from __future__ import annotations

from dataclasses import dataclass, field

from seedwork.domain.types import JsonDict

from ip.engine.domain.exceptions import CodecError, IpError, Result


@dataclass(frozen=True, kw_only=True)
class EmitNotificationStepInput:
    """Strongly-typed input DTO for Stage-1 notification ingestion (`notification.requested`)."""

    channel: str
    template_id: str
    recipient: str
    variables: JsonDict = field(default_factory=dict)

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[EmitNotificationStepInput, IpError]:
        channel = data.get("channel")
        template_id = data.get("template_id")
        recipient = data.get("recipient")
        raw_vars = data.get("variables")
        if (
            not isinstance(channel, str)
            or not channel.strip()
            or not isinstance(template_id, str)
            or not template_id.strip()
            or not isinstance(recipient, str)
            or not recipient.strip()
        ):
            return Result.err(
                CodecError.with_message(
                    "EmitNotificationStepInput requires non-empty channel, template_id, and recipient."
                )
            )
        variables: JsonDict = dict(raw_vars) if isinstance(raw_vars, dict) else {}
        return Result.ok(
            cls(
                channel=channel,
                template_id=template_id,
                recipient=recipient,
                variables=variables,
            )
        )


@dataclass(frozen=True, kw_only=True)
class EmitNotificationStepOutput:
    """Strongly-typed output DTO after queueing a Stage-1 notification event."""

    envelope_id: str
    event_type: str

    def to_payload(self) -> JsonDict:
        return {
            "envelope_id": self.envelope_id,
            "event_type": self.event_type,
        }


__all__ = [
    "EmitNotificationStepInput",
    "EmitNotificationStepOutput",
]
