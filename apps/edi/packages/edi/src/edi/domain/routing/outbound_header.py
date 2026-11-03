"""EDI Headers and Envelope Behavioral Domain Models."""

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

__all__ = [
    "EdiEnvelopeHeaders",
    "OutboundEdiHeader",
]


@dataclass(kw_only=True, eq=False)
class OutboundEdiHeader(AggregateRoot):
    """Behavioral Aggregate Root governing Trading Partner EDI envelope header parameters."""

    ID_PREFIX = DomainIdPrefix.EDI_OUTBOUND_HEADER.value

    id: str
    tenant_id: str
    trading_partner_id: str
    isa_sender_id: str
    isa_receiver_id: str
    created_at: datetime
    updated_at: datetime
    name: str | None = None
    isa_sender_qualifier: str | None = None
    isa_receiver_qualifier: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None
    default_standard: str | None = None
    default_version: str | None = None
    isa_control_version: str | None = None
    isa_usage_indicator: str | None = None
    gs_version: str | None = None
    segment_terminator: str | None = None
    element_separator: str | None = None
    subelement_separator: str | None = None

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        trading_partner_id: str,
        isa_sender_id: str,
        isa_receiver_id: str,
        id: str | None = None,
        name: str | None = None,
        isa_sender_qualifier: str | None = None,
        isa_receiver_qualifier: str | None = None,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
        transaction_type: str | None = None,
        default_standard: str | None = None,
        default_version: str | None = None,
        isa_control_version: str | None = None,
        isa_usage_indicator: str | None = None,
        gs_version: str | None = None,
        segment_terminator: str | None = None,
        element_separator: str | None = None,
        subelement_separator: str | None = None,
        idempotency_key: str | None = None,
    ) -> Result[OutboundEdiHeader, EdiRoutingError]:
        """Create an OutboundEdiHeader aggregate with required identifier invariants."""
        if (
            not trading_partner_id
            or not trading_partner_id.strip()
            or not isa_sender_id
            or not isa_sender_id.strip()
            or not isa_receiver_id
            or not isa_receiver_id.strip()
        ):
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.INVALID_MATCHING_CRITERIA,
                    message="trading_partner_id, isa_sender_id, and isa_receiver_id must be non-empty.",
                    details={
                        "trading_partner_id": trading_partner_id,
                        "isa_sender_id": isa_sender_id,
                        "isa_receiver_id": isa_receiver_id,
                    },
                )
            )

        header_id = id or cls.new_id()
        now = datetime.now(UTC)
        header = cls(
            id=header_id,
            tenant_id=tenant_id,
            trading_partner_id=trading_partner_id,
            isa_sender_id=isa_sender_id,
            isa_receiver_id=isa_receiver_id,
            created_at=now,
            updated_at=now,
            name=name,
            isa_sender_qualifier=isa_sender_qualifier,
            isa_receiver_qualifier=isa_receiver_qualifier,
            gs_sender_id=gs_sender_id,
            gs_receiver_id=gs_receiver_id,
            transaction_type=transaction_type,
            default_standard=default_standard,
            default_version=default_version,
            isa_control_version=isa_control_version,
            isa_usage_indicator=isa_usage_indicator,
            gs_version=gs_version,
            segment_terminator=segment_terminator,
            element_separator=element_separator,
            subelement_separator=subelement_separator,
        )
        header.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_header_created,
                resource_id=header_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(header)

    def update(
        self,
        *,
        trading_partner_id: str | UnsetType = UNSET,
        isa_sender_id: str | UnsetType = UNSET,
        isa_receiver_id: str | UnsetType = UNSET,
        name: str | UnsetType | None = UNSET,
        isa_sender_qualifier: str | UnsetType | None = UNSET,
        isa_receiver_qualifier: str | UnsetType | None = UNSET,
        gs_sender_id: str | UnsetType | None = UNSET,
        gs_receiver_id: str | UnsetType | None = UNSET,
        transaction_type: str | UnsetType | None = UNSET,
        default_standard: str | UnsetType | None = UNSET,
        default_version: str | UnsetType | None = UNSET,
        isa_control_version: str | UnsetType | None = UNSET,
        isa_usage_indicator: str | UnsetType | None = UNSET,
        gs_version: str | UnsetType | None = UNSET,
        segment_terminator: str | UnsetType | None = UNSET,
        element_separator: str | UnsetType | None = UNSET,
        subelement_separator: str | UnsetType | None = UNSET,
        idempotency_key: str | None = None,
    ) -> Result[OutboundEdiHeader, EdiRoutingError]:
        """Validate and update outbound EDI header attributes atomically."""
        if not isinstance(trading_partner_id, UnsetType) and not trading_partner_id.strip():
            return Result.fail(
                EdiRoutingError(
                    code=EdiErrorCode.INVALID_MATCHING_CRITERIA,
                    message="trading_partner_id cannot be blank.",
                )
            )
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

        next_trading_partner_id = resolve_unset(trading_partner_id, self.trading_partner_id)
        next_isa_sender_id = resolve_unset(isa_sender_id, self.isa_sender_id)
        next_isa_receiver_id = resolve_unset(isa_receiver_id, self.isa_receiver_id)
        next_name = resolve_unset(name, self.name)
        next_isa_sender_qualifier = resolve_unset(isa_sender_qualifier, self.isa_sender_qualifier)
        next_isa_receiver_qualifier = resolve_unset(
            isa_receiver_qualifier, self.isa_receiver_qualifier
        )
        next_gs_sender_id = resolve_unset(gs_sender_id, self.gs_sender_id)
        next_gs_receiver_id = resolve_unset(gs_receiver_id, self.gs_receiver_id)
        next_transaction_type = resolve_unset(transaction_type, self.transaction_type)
        next_default_standard = resolve_unset(default_standard, self.default_standard)
        next_default_version = resolve_unset(default_version, self.default_version)
        next_isa_control_version = resolve_unset(isa_control_version, self.isa_control_version)
        next_isa_usage_indicator = resolve_unset(isa_usage_indicator, self.isa_usage_indicator)
        next_gs_version = resolve_unset(gs_version, self.gs_version)
        next_segment_terminator = resolve_unset(segment_terminator, self.segment_terminator)
        next_element_separator = resolve_unset(element_separator, self.element_separator)
        next_subelement_separator = resolve_unset(subelement_separator, self.subelement_separator)

        if (
            next_trading_partner_id,
            next_isa_sender_id,
            next_isa_receiver_id,
            next_name,
            next_isa_sender_qualifier,
            next_isa_receiver_qualifier,
            next_gs_sender_id,
            next_gs_receiver_id,
            next_transaction_type,
            next_default_standard,
            next_default_version,
            next_isa_control_version,
            next_isa_usage_indicator,
            next_gs_version,
            next_segment_terminator,
            next_element_separator,
            next_subelement_separator,
        ) == (
            self.trading_partner_id,
            self.isa_sender_id,
            self.isa_receiver_id,
            self.name,
            self.isa_sender_qualifier,
            self.isa_receiver_qualifier,
            self.gs_sender_id,
            self.gs_receiver_id,
            self.transaction_type,
            self.default_standard,
            self.default_version,
            self.isa_control_version,
            self.isa_usage_indicator,
            self.gs_version,
            self.segment_terminator,
            self.element_separator,
            self.subelement_separator,
        ):
            return Result.ok(self)

        self.trading_partner_id = next_trading_partner_id
        self.isa_sender_id = next_isa_sender_id
        self.isa_receiver_id = next_isa_receiver_id
        self.name = next_name
        self.isa_sender_qualifier = next_isa_sender_qualifier
        self.isa_receiver_qualifier = next_isa_receiver_qualifier
        self.gs_sender_id = next_gs_sender_id
        self.gs_receiver_id = next_gs_receiver_id
        self.transaction_type = next_transaction_type
        self.default_standard = next_default_standard
        self.default_version = next_default_version
        self.isa_control_version = next_isa_control_version
        self.isa_usage_indicator = next_isa_usage_indicator
        self.gs_version = next_gs_version
        self.segment_terminator = next_segment_terminator
        self.element_separator = next_element_separator
        self.subelement_separator = next_subelement_separator

        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_header_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def mark_deleted(
        self, idempotency_key: str | None = None
    ) -> Result[OutboundEdiHeader, EdiRoutingError]:
        """Emit deletion provisioning event for OutboundEdiHeader."""
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_header_deleted,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def to_envelope_headers(self, fallback_transaction_type: str) -> EdiEnvelopeHeaders:
        """Project this aggregate's interchange configuration into an immutable EdiEnvelopeHeaders VO."""
        return EdiEnvelopeHeaders(
            isa_sender_id=self.isa_sender_id,
            isa_receiver_id=self.isa_receiver_id,
            transaction_type=self.transaction_type or fallback_transaction_type,
            gs_sender_id=self.gs_sender_id,
            gs_receiver_id=self.gs_receiver_id,
            isa_usage_indicator=self.isa_usage_indicator,
            isa_sender_qualifier=self.isa_sender_qualifier,
            isa_receiver_qualifier=self.isa_receiver_qualifier,
            default_version=self.default_version,
            segment_terminator=self.segment_terminator,
            element_separator=self.element_separator,
            subelement_separator=self.subelement_separator,
        )


@dataclass(frozen=True, kw_only=True)
class EdiEnvelopeHeaders:
    """Domain Value Object representing the resolved EDI envelope parameters.

    This is the minimal, immutable set of X12/EDIFACT segment fields required
    to physically construct an ISA/GS (X12) or UNB (EDIFACT) interchange envelope.

    It is NOT a database model. It is produced by a use case after resolving the
    full OutboundEdiHeader for a trading partner, and is passed into
    the TransformerPort to drive envelope generation.
    """

    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    isa_usage_indicator: str | None = None
    isa_sender_qualifier: str | None = None
    isa_receiver_qualifier: str | None = None
    default_version: str | None = None
    segment_terminator: str | None = None
    element_separator: str | None = None
    subelement_separator: str | None = None
