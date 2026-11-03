"""Inbound Route Behavioral Aggregate Root."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, UnsetType, resolve_defined, resolve_unset
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.exceptions import EdiErrorCode, EdiRoutingError
from edi.domain.routing.destination import RouteDestination
from edi.domain.routing.enums import (
    EdiConnectionType,
    EdiDirection,
    OutboundRouteType,
    ProcessingMode,
)

__all__ = ["InboundRoute"]


@dataclass(kw_only=True, eq=False)
class InboundRoute(AggregateRoot):
    """Behavioral Aggregate Root governing Inbound EDI Route ingress matching and destination dispatch."""

    ID_PREFIX = DomainIdPrefix.EDI_INBOUND_ROUTE.value

    id: str
    tenant_id: str
    name: str | None = None
    isa_sender_id: str
    isa_receiver_id: str
    active: bool
    created_at: datetime
    updated_at: datetime
    trading_partner_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None
    processing_mode: ProcessingMode | None = None
    direction: EdiDirection = EdiDirection.INBOUND
    destination: RouteDestination | None = None

    def __init__(
        self,
        *,
        id: str,
        tenant_id: str,
        name: str | None = None,
        isa_sender_id: str,
        isa_receiver_id: str,
        active: bool,
        created_at: datetime,
        updated_at: datetime,
        trading_partner_id: str | None = None,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
        transaction_type: str | None = None,
        processing_mode: ProcessingMode | None = None,
        direction: EdiDirection = EdiDirection.INBOUND,
        destination: RouteDestination | None = None,
        webhook_id: str | None = None,
        as2_partner_id: str | None = None,
        sftp_partner_id: str | None = None,
        connection_type: EdiConnectionType | None = None,
        destination_name: str | None = None,
    ) -> None:
        super().__init__()
        self.id = id
        self.tenant_id = tenant_id
        self.name = name
        self.isa_sender_id = isa_sender_id
        self.isa_receiver_id = isa_receiver_id
        self.active = active
        self.created_at = created_at
        self.updated_at = updated_at
        self.trading_partner_id = trading_partner_id
        self.gs_sender_id = gs_sender_id
        self.gs_receiver_id = gs_receiver_id
        self.transaction_type = transaction_type
        self.processing_mode = processing_mode
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
    def webhook_id(self) -> str | None:
        if self.destination and self.destination.target_type == OutboundRouteType.WEBHOOK:
            return self.destination.target_id
        return None

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
        isa_sender_id: str,
        isa_receiver_id: str,
        id: str | None = None,
        name: str | None = None,
        trading_partner_id: str | None = None,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
        transaction_type: str | None = None,
        processing_mode: ProcessingMode | None = None,
        destination: RouteDestination | None = None,
        webhook_id: str | None = None,
        as2_partner_id: str | None = None,
        sftp_partner_id: str | None = None,
        connection_type: EdiConnectionType | None = None,
        destination_name: str | None = None,
        idempotency_key: str | None = None,
    ) -> Result[InboundRoute, EdiRoutingError]:
        """Create a new Inbound Route aggregate with invariant verification."""
        if (
            not isa_sender_id
            or not isa_sender_id.strip()
            or not isa_receiver_id
            or not isa_receiver_id.strip()
        ):
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.INVALID_MATCHING_CRITERIA,
                    message="isa_sender_id and isa_receiver_id must be non-empty strings.",
                    details={
                        "isa_sender_id": isa_sender_id,
                        "isa_receiver_id": isa_receiver_id,
                    },
                )
            )

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
            name=name,
            isa_sender_id=isa_sender_id,
            isa_receiver_id=isa_receiver_id,
            active=False,
            created_at=now,
            updated_at=now,
            trading_partner_id=trading_partner_id,
            gs_sender_id=gs_sender_id,
            gs_receiver_id=gs_receiver_id,
            transaction_type=transaction_type,
            processing_mode=processing_mode,
            direction=EdiDirection.INBOUND,
            destination=resolved_dest,
        )

        route.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_inbound_route_created,
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
        webhook_id: str | None = None,
        as2_partner_id: str | None = None,
        sftp_partner_id: str | None = None,
        connection_type: EdiConnectionType | None = None,
        destination_name: str | None = None,
        idempotency_key: str | None = None,
    ) -> Result[InboundRoute, EdiRoutingError]:
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
                event_type=EdiEventType.edi_inbound_route_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def activate(self, idempotency_key: str | None = None) -> Result[InboundRoute, EdiRoutingError]:
        """Activate the inbound route."""
        if self.active:
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.ROUTE_ALREADY_ACTIVE,
                    message=f"Inbound route '{self.id}' is already active.",
                    details={"route_id": self.id},
                )
            )
        self.active = True
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_inbound_route_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def deactivate(
        self, idempotency_key: str | None = None
    ) -> Result[InboundRoute, EdiRoutingError]:
        """Deactivate the inbound route."""
        if not self.active:
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.ROUTE_ALREADY_INACTIVE,
                    message=f"Inbound route '{self.id}' is already inactive.",
                    details={"route_id": self.id},
                )
            )
        self.active = False
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_inbound_route_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def update_matching_criteria(
        self,
        *,
        isa_sender_id: str | None = None,
        isa_receiver_id: str | None = None,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
        transaction_type: str | None = None,
        processing_mode: ProcessingMode | None = None,
        name: str | None = None,
        trading_partner_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Result[InboundRoute, EdiRoutingError]:
        """Update matching criteria while validating non-empty identifiers."""
        if isa_sender_id is not None and not isa_sender_id.strip():
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.INVALID_MATCHING_CRITERIA,
                    message="isa_sender_id cannot be blank.",
                )
            )
        if isa_receiver_id is not None and not isa_receiver_id.strip():
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.INVALID_MATCHING_CRITERIA,
                    message="isa_receiver_id cannot be blank.",
                )
            )

        self.isa_sender_id = resolve_defined(isa_sender_id, self.isa_sender_id)
        self.isa_receiver_id = resolve_defined(isa_receiver_id, self.isa_receiver_id)
        self.gs_sender_id = resolve_defined(gs_sender_id, self.gs_sender_id)
        self.gs_receiver_id = resolve_defined(gs_receiver_id, self.gs_receiver_id)
        self.transaction_type = resolve_defined(transaction_type, self.transaction_type)
        self.processing_mode = resolve_defined(processing_mode, self.processing_mode)
        self.name = resolve_defined(name, self.name)
        self.trading_partner_id = resolve_defined(trading_partner_id, self.trading_partner_id)

        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_inbound_route_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def _resolve_updated_destination(
        self,
        *,
        webhook_id: str | UnsetType | None,
        as2_partner_id: str | UnsetType | None,
        sftp_partner_id: str | UnsetType | None,
        connection_type: EdiConnectionType | UnsetType | None,
    ) -> Result[RouteDestination | None, EdiRoutingError]:
        has_dest_update = any(
            not isinstance(v, UnsetType)
            for v in (webhook_id, as2_partner_id, sftp_partner_id, connection_type)
        )
        if not has_dest_update:
            return Result.ok(self.destination)

        dest_res = RouteDestination.from_targets(
            webhook_id=resolve_unset(webhook_id, self.webhook_id),
            as2_partner_id=resolve_unset(as2_partner_id, self.as2_partner_id),
            sftp_partner_id=resolve_unset(sftp_partner_id, self.sftp_partner_id),
            connection_type=resolve_unset(connection_type, None),
            destination_name=self.destination_name,
        )
        if dest_res.is_err:
            return Result.fail(dest_res.unwrap_err())
        return Result.ok(dest_res.unwrap())

    def update(
        self,
        *,
        isa_sender_id: str | UnsetType = UNSET,
        isa_receiver_id: str | UnsetType = UNSET,
        gs_sender_id: str | UnsetType | None = UNSET,
        gs_receiver_id: str | UnsetType | None = UNSET,
        transaction_type: str | UnsetType | None = UNSET,
        processing_mode: ProcessingMode | UnsetType | None = UNSET,
        name: str | UnsetType | None = UNSET,
        trading_partner_id: str | UnsetType | None = UNSET,
        webhook_id: str | UnsetType | None = UNSET,
        as2_partner_id: str | UnsetType | None = UNSET,
        sftp_partner_id: str | UnsetType | None = UNSET,
        connection_type: EdiConnectionType | UnsetType | None = UNSET,
        active: bool | UnsetType = UNSET,
        idempotency_key: str | None = None,
    ) -> Result[InboundRoute, EdiRoutingError]:
        """Atomically validate and apply inbound route updates, emitting a single ProvisioningEvent."""
        if not isinstance(isa_sender_id, UnsetType) and not isa_sender_id.strip():
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.INVALID_MATCHING_CRITERIA,
                    message="isa_sender_id cannot be blank.",
                )
            )
        if not isinstance(isa_receiver_id, UnsetType) and not isa_receiver_id.strip():
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.INVALID_MATCHING_CRITERIA,
                    message="isa_receiver_id cannot be blank.",
                )
            )

        dest_res = self._resolve_updated_destination(
            webhook_id=webhook_id,
            as2_partner_id=as2_partner_id,
            sftp_partner_id=sftp_partner_id,
            connection_type=connection_type,
        )
        if dest_res.is_err:
            return Result.fail(dest_res.unwrap_err())

        next_destination = dest_res.unwrap()
        next_isa_sender_id = resolve_unset(isa_sender_id, self.isa_sender_id)
        next_isa_receiver_id = resolve_unset(isa_receiver_id, self.isa_receiver_id)
        next_gs_sender_id = resolve_unset(gs_sender_id, self.gs_sender_id)
        next_gs_receiver_id = resolve_unset(gs_receiver_id, self.gs_receiver_id)
        next_transaction_type = resolve_unset(transaction_type, self.transaction_type)
        next_processing_mode = resolve_unset(processing_mode, self.processing_mode)
        next_name = resolve_unset(name, self.name)
        next_trading_partner_id = resolve_unset(trading_partner_id, self.trading_partner_id)
        next_active = resolve_unset(active, self.active)

        if (
            next_destination,
            next_isa_sender_id,
            next_isa_receiver_id,
            next_gs_sender_id,
            next_gs_receiver_id,
            next_transaction_type,
            next_processing_mode,
            next_name,
            next_trading_partner_id,
            next_active,
        ) == (
            self.destination,
            self.isa_sender_id,
            self.isa_receiver_id,
            self.gs_sender_id,
            self.gs_receiver_id,
            self.transaction_type,
            self.processing_mode,
            self.name,
            self.trading_partner_id,
            self.active,
        ):
            return Result.ok(self)

        self.destination = next_destination
        self.isa_sender_id = next_isa_sender_id
        self.isa_receiver_id = next_isa_receiver_id
        self.gs_sender_id = next_gs_sender_id
        self.gs_receiver_id = next_gs_receiver_id
        self.transaction_type = next_transaction_type
        self.processing_mode = next_processing_mode
        self.name = next_name
        self.trading_partner_id = next_trading_partner_id
        self.active = next_active

        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_inbound_route_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def mark_deleted(
        self, idempotency_key: str | None = None
    ) -> Result[InboundRoute, EdiRoutingError]:
        """Mark the inbound route as deleted and emit its deletion provisioning event."""
        self.active = False
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_inbound_route_deleted,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)
