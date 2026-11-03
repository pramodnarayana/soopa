"""Domain Value Objects for Route Destinations."""

from __future__ import annotations

from dataclasses import dataclass

from seedwork.domain.exceptions import Result

from edi.domain.exceptions import EdiErrorCode, EdiRoutingError
from edi.domain.routing.enums import EdiConnectionType, OutboundRouteType

__all__ = ["RouteDestination"]


@dataclass(frozen=True)
class RouteDestination:
    """Immutable Domain Value Object encapsulating a route's egress target.

    Guarantees mutual exclusivity by construction: a route has at most one
    target destination (`WEBHOOK`, `AS2`, or `SFTP`) with its associated
    logical `connection_type` and optional display name.
    """

    target_id: str
    connection_type: EdiConnectionType
    target_type: OutboundRouteType | None = None
    destination_name: str | None = None

    def __post_init__(self) -> None:
        if self.target_type is None:
            if self.connection_type == EdiConnectionType.AS2:
                object.__setattr__(self, "target_type", OutboundRouteType.AS2)
            elif self.connection_type == EdiConnectionType.SFTP:
                object.__setattr__(self, "target_type", OutboundRouteType.SFTP)
            else:
                object.__setattr__(self, "target_type", OutboundRouteType.WEBHOOK)

    @classmethod
    def for_webhook(cls, webhook_id: str, destination_name: str | None = None) -> RouteDestination:
        return cls(
            target_id=webhook_id,
            target_type=OutboundRouteType.WEBHOOK,
            connection_type=EdiConnectionType.WEBHOOK,
            destination_name=destination_name,
        )

    @classmethod
    def for_as2(cls, as2_partner_id: str, destination_name: str | None = None) -> RouteDestination:
        return cls(
            target_id=as2_partner_id,
            target_type=OutboundRouteType.AS2,
            connection_type=EdiConnectionType.AS2,
            destination_name=destination_name,
        )

    @classmethod
    def for_sftp(
        cls, sftp_partner_id: str, destination_name: str | None = None
    ) -> RouteDestination:
        return cls(
            target_id=sftp_partner_id,
            target_type=OutboundRouteType.SFTP,
            connection_type=EdiConnectionType.SFTP,
            destination_name=destination_name,
        )

    @classmethod
    def from_targets(
        cls,
        *,
        webhook_id: str | None = None,
        as2_partner_id: str | None = None,
        sftp_partner_id: str | None = None,
        connection_type: EdiConnectionType | None = None,
        destination_name: str | None = None,
    ) -> Result[RouteDestination, EdiRoutingError]:
        """Validate mutual exclusivity and construct a RouteDestination Value Object."""
        targets = [
            (webhook_id, OutboundRouteType.WEBHOOK, EdiConnectionType.WEBHOOK),
            (as2_partner_id, OutboundRouteType.AS2, EdiConnectionType.AS2),
            (sftp_partner_id, OutboundRouteType.SFTP, EdiConnectionType.SFTP),
        ]
        non_empty = [
            (str(tid), ttype, ctype)
            for tid, ttype, ctype in targets
            if tid is not None and str(tid).strip()
        ]

        if len(non_empty) > 1:
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.INVALID_DESTINATION_MUTUAL_EXCLUSIVITY,
                    message="At most one active destination (webhook_id, as2_partner_id, sftp_partner_id) may be specified.",
                    details={
                        "webhook_id": webhook_id,
                        "as2_partner_id": as2_partner_id,
                        "sftp_partner_id": sftp_partner_id,
                    },
                )
            )

        if not non_empty:
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="At least one target destination must be provided.",
                )
            )

        tid, ttype, derived_conn = non_empty[0]
        actual_conn = connection_type or derived_conn
        return Result.ok(
            cls(
                target_id=tid,
                target_type=ttype,
                connection_type=actual_conn,
                destination_name=destination_name,
            )
        )

    @classmethod
    def from_optional(
        cls,
        *,
        webhook_id: str | None = None,
        as2_partner_id: str | None = None,
        sftp_partner_id: str | None = None,
        connection_type: EdiConnectionType | None = None,
        destination_name: str | None = None,
    ) -> RouteDestination | None:
        """Hydrate optional database record targets into a RouteDestination if any target exists."""
        targets = [
            (as2_partner_id, OutboundRouteType.AS2, EdiConnectionType.AS2),
            (sftp_partner_id, OutboundRouteType.SFTP, EdiConnectionType.SFTP),
            (webhook_id, OutboundRouteType.WEBHOOK, EdiConnectionType.WEBHOOK),
        ]
        non_empty = [
            (str(tid), ttype, ctype)
            for tid, ttype, ctype in targets
            if tid is not None and str(tid).strip()
        ]
        if not non_empty:
            return None
        tid, ttype, derived_conn = non_empty[0]
        actual_conn = connection_type or derived_conn
        return cls(
            target_id=tid,
            target_type=ttype,
            connection_type=actual_conn,
            destination_name=destination_name,
        )
