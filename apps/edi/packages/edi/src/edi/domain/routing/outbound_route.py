"""Outbound Route Behavioral Aggregate Root."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, UnsetType, resolve_unset
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.exceptions import EdiErrorCode, EdiRoutingError
from edi.domain.routing.destination import RouteDestination
from edi.domain.routing.enums import EdiConnectionType, EdiDirection, OutboundRouteType

__all__ = ["OutboundRoute"]


@dataclass(kw_only=True, eq=False)
class OutboundRoute(AggregateRoot):
    """Behavioral Aggregate Root governing Outbound EDI Route egress destination resolution."""

    ID_PREFIX = DomainIdPrefix.EDI_OUTBOUND_ROUTE.value

    id: str
    tenant_id: str
    trading_partner_id: str | None = None
    name: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime
    direction: EdiDirection = EdiDirection.OUTBOUND
    destination: RouteDestination | None = None

    def __init__(
        self,
        *,
        id: str,
        tenant_id: str,
        trading_partner_id: str | None = None,
        name: str | None = None,
        active: bool,
        created_at: datetime,
        updated_at: datetime,
        direction: EdiDirection = EdiDirection.OUTBOUND,
        destination: RouteDestination | None = None,
        as2_partner_id: str | None = None,
        sftp_partner_id: str | None = None,
        webhook_id: str | None = None,
        connection_type: EdiConnectionType | None = None,
        destination_name: str | None = None,
    ) -> None:
        super().__init__()
        self.id = id
        self.tenant_id = tenant_id
        self.trading_partner_id = trading_partner_id
        self.name = name
        self.active = active
        self.created_at = created_at
        self.updated_at = updated_at
        self.direction = direction

        if destination is not None:
            self.destination = destination
        else:
            self.destination = RouteDestination.from_optional(
                webhook_id=webhook_id,
                as2_partner_id=as2_partner_id,
                sftp_partner_id=sftp_partner_id,
                connection_type=connection_type,
                destination_name=destination_name,
            )

    # --- Destination Value Object Projections ---

    @property
    def as2_partner_id(self) -> str | None:
        if self.destination and self.destination.target_type == OutboundRouteType.AS2:
            return self.destination.target_id
        return None

    @property
    def sftp_partner_id(self) -> str | None:
        if self.destination and self.destination.target_type == OutboundRouteType.SFTP:
            return self.destination.target_id
        return None

    @property
    def webhook_id(self) -> str | None:
        if self.destination and self.destination.target_type == OutboundRouteType.WEBHOOK:
            return self.destination.target_id
        return None

    @property
    def connection_type(self) -> EdiConnectionType | None:
        return self.destination.connection_type if self.destination else None

    @property
    def destination_name(self) -> str | None:
        return self.destination.destination_name if self.destination else None

    # --- Behavioral Aggregate Factory ---

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        id: str | None = None,
        name: str | None = None,
        trading_partner_id: str | None = None,
        destination: RouteDestination | None = None,
        as2_partner_id: str | None = None,
        sftp_partner_id: str | None = None,
        webhook_id: str | None = None,
        connection_type: EdiConnectionType | None = None,
        destination_name: str | None = None,
        idempotency_key: str | None = None,
    ) -> Result[OutboundRoute, EdiRoutingError]:
        """Create a new Outbound Route aggregate enforcing destination exclusivity."""
        resolved_dest = destination
        if resolved_dest is None:
            dest_res = RouteDestination.from_targets(
                webhook_id=webhook_id,
                as2_partner_id=as2_partner_id,
                sftp_partner_id=sftp_partner_id,
                connection_type=connection_type,
                destination_name=destination_name,
            )
            if dest_res.is_err:
                if (
                    dest_res.unwrap_err().code
                    == EdiErrorCode.INVALID_DESTINATION_MUTUAL_EXCLUSIVITY
                ):
                    return Result.fail(dest_res.unwrap_err())
                resolved_dest = None
            else:
                resolved_dest = dest_res.unwrap()

        route_id = id or cls.new_id()
        now = datetime.now(UTC)

        route = cls(
            id=route_id,
            tenant_id=tenant_id,
            trading_partner_id=trading_partner_id,
            name=name,
            active=False,
            created_at=now,
            updated_at=now,
            direction=EdiDirection.OUTBOUND,
            destination=resolved_dest,
        )

        route.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_outbound_route_created,
                resource_id=route_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(route)

    # --- Aggregate Mutations & Invariants ---

    def bind_destination(
        self,
        destination: RouteDestination | None = None,
        *,
        as2_partner_id: str | None = None,
        sftp_partner_id: str | None = None,
        webhook_id: str | None = None,
        connection_type: EdiConnectionType | None = None,
        destination_name: str | None = None,
        idempotency_key: str | None = None,
    ) -> Result[OutboundRoute, EdiRoutingError]:
        """Atomically switch destination target ensuring mutual exclusivity via Value Object."""
        if destination is not None:
            self.destination = destination
        else:
            dest_res = RouteDestination.from_targets(
                webhook_id=webhook_id,
                as2_partner_id=as2_partner_id,
                sftp_partner_id=sftp_partner_id,
                connection_type=connection_type,
                destination_name=destination_name,
            )
            if dest_res.is_err:
                return Result.fail(dest_res.unwrap_err())
            self.destination = dest_res.unwrap()

        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_outbound_route_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def activate(
        self, idempotency_key: str | None = None
    ) -> Result[OutboundRoute, EdiRoutingError]:
        """Activate the outbound route."""
        if self.active:
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.ROUTE_ALREADY_ACTIVE,
                    message=f"Outbound route '{self.id}' is already active.",
                    details={"route_id": self.id},
                )
            )
        self.active = True
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_outbound_route_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def deactivate(
        self, idempotency_key: str | None = None
    ) -> Result[OutboundRoute, EdiRoutingError]:
        """Deactivate the outbound route."""
        if not self.active:
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.ROUTE_ALREADY_INACTIVE,
                    message=f"Outbound route '{self.id}' is already inactive.",
                    details={"route_id": self.id},
                )
            )
        self.active = False
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_outbound_route_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def update(
        self,
        *,
        name: str | UnsetType | None = UNSET,
        trading_partner_id: str | UnsetType | None = UNSET,
        as2_partner_id: str | UnsetType | None = UNSET,
        sftp_partner_id: str | UnsetType | None = UNSET,
        webhook_id: str | UnsetType | None = UNSET,
        connection_type: EdiConnectionType | UnsetType | None = UNSET,
        active: bool | UnsetType = UNSET,
        idempotency_key: str | None = None,
    ) -> Result[OutboundRoute, EdiRoutingError]:
        """Atomically update outbound route attributes and destination, emitting one ProvisioningEvent."""
        next_destination = self.destination
        has_dest_update = any(
            not isinstance(v, UnsetType)
            for v in (as2_partner_id, sftp_partner_id, webhook_id, connection_type)
        )
        if has_dest_update:
            dest_res = RouteDestination.from_targets(
                webhook_id=resolve_unset(webhook_id, self.webhook_id),
                as2_partner_id=resolve_unset(as2_partner_id, self.as2_partner_id),
                sftp_partner_id=resolve_unset(sftp_partner_id, self.sftp_partner_id),
                connection_type=resolve_unset(connection_type, None),
                destination_name=self.destination_name,
            )
            if dest_res.is_err:
                return Result.fail(dest_res.unwrap_err())
            next_destination = dest_res.unwrap()

        next_name = resolve_unset(name, self.name)
        next_trading_partner_id = resolve_unset(trading_partner_id, self.trading_partner_id)
        next_active = resolve_unset(active, self.active)

        if (
            next_destination,
            next_name,
            next_trading_partner_id,
            next_active,
        ) == (
            self.destination,
            self.name,
            self.trading_partner_id,
            self.active,
        ):
            return Result.ok(self)

        self.destination = next_destination
        self.name = next_name
        self.trading_partner_id = next_trading_partner_id
        self.active = next_active

        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_outbound_route_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def mark_deleted(
        self, idempotency_key: str | None = None
    ) -> Result[OutboundRoute, EdiRoutingError]:
        """Mark the outbound route as deleted and emit its deletion provisioning event."""
        self.active = False
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_outbound_route_deleted,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)
