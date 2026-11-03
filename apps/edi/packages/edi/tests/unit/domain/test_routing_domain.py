"""Unit tests for EDI Routing Behavioral Aggregates and Read-Only Webhook Value Object.

Verifies:
- InboundRoute, OutboundRoute, OutboundEdiHeader aggregates, and read-only Webhook Value Object
- Destination mutual exclusivity enforcement (bind_destination & atomic update)
- Timezone-aware UTC timestamps, identity equality, and no-op update guards
- Invariant validation returning Result[T, EdiRoutingError] without exceptions
- Internal DomainEvent recording via self.add_domain_event()
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest
from seedwork.domain.types import UNSET
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from edi.domain.constants import EdiIdPrefix
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.exceptions import EdiErrorCode, EdiRoutingError
from edi.domain.routing.destination import RouteDestination
from edi.domain.routing.enums import EdiConnectionType, EdiDirection, ProcessingMode
from edi.domain.routing.inbound_route import InboundRoute
from edi.domain.routing.outbound_header import EdiEnvelopeHeaders, OutboundEdiHeader
from edi.domain.routing.outbound_route import OutboundRoute
from edi.domain.routing.webhook import Webhook


def test_inbound_route_creation_success_with_single_destination() -> None:
    tenant_id = generate_id(EdiIdPrefix.TENANT)
    webhook_id = generate_id(EdiIdPrefix.EDI_WEBHOOK)

    result = InboundRoute.create(
        tenant_id=tenant_id,
        isa_sender_id="SENDER1",
        isa_receiver_id="RECEIVER1",
        transaction_type="850",
        webhook_id=webhook_id,
        name="Purchase Orders Route",
        processing_mode=ProcessingMode.TRANSFORM,
    )

    assert result.is_ok
    route = result.unwrap()
    assert route.id.startswith("edi_inb_rt_")
    assert route.tenant_id == tenant_id
    assert route.isa_sender_id == "SENDER1"
    assert route.isa_receiver_id == "RECEIVER1"
    assert route.transaction_type == "850"
    assert route.webhook_id == webhook_id
    assert route.as2_partner_id is None
    assert route.sftp_partner_id is None
    assert route.connection_type == EdiConnectionType.WEBHOOK
    assert route.direction == EdiDirection.INBOUND
    assert route.active is False
    assert route.created_at.tzinfo is not None
    assert route.updated_at.tzinfo is not None
    assert route != replace(route)
    assert isinstance(hash(route), int)

    events = route.pull_domain_events()
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ProvisioningEvent)
    assert event.event_type == EdiEventType.edi_inbound_route_created
    assert event.tenant_id == tenant_id
    assert event.resource_id == route.id


def test_inbound_route_creation_fails_when_multiple_destinations_specified() -> None:
    tenant_id = generate_id(EdiIdPrefix.TENANT)
    webhook_id = generate_id(EdiIdPrefix.EDI_WEBHOOK)
    as2_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)

    result = InboundRoute.create(
        tenant_id=tenant_id,
        isa_sender_id="SENDER1",
        isa_receiver_id="RECEIVER1",
        webhook_id=webhook_id,
        as2_partner_id=as2_partner_id,
    )

    assert result.is_err
    error = result.unwrap_err()
    assert isinstance(error, EdiRoutingError)
    assert error.code == EdiErrorCode.INVALID_DESTINATION_MUTUAL_EXCLUSIVITY


def test_inbound_route_creation_fails_when_sender_or_receiver_is_blank() -> None:
    result = InboundRoute.create(
        tenant_id=generate_id(EdiIdPrefix.TENANT),
        isa_sender_id="",
        isa_receiver_id="RECEIVER1",
        webhook_id=generate_id(EdiIdPrefix.EDI_WEBHOOK),
    )
    assert result.is_err
    assert result.unwrap_err().code == EdiErrorCode.INVALID_MATCHING_CRITERIA


def test_inbound_route_bind_destination_switches_target_and_emits_event() -> None:
    as2_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)
    route = InboundRoute.create(
        tenant_id=generate_id(EdiIdPrefix.TENANT),
        isa_sender_id="SENDER1",
        isa_receiver_id="RECEIVER1",
        webhook_id=generate_id(EdiIdPrefix.EDI_WEBHOOK),
    ).unwrap()
    _ = route.pull_domain_events()

    bind_res = route.bind_destination(
        as2_partner_id=as2_partner_id,
        destination_name="Acme AS2 Target",
    )
    assert bind_res.is_ok
    assert route.webhook_id is None
    assert route.as2_partner_id == as2_partner_id
    assert route.sftp_partner_id is None
    assert route.connection_type == EdiConnectionType.AS2
    assert route.destination_name == "Acme AS2 Target"

    events = route.pull_domain_events()
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ProvisioningEvent)
    assert event.event_type == EdiEventType.edi_inbound_route_updated


def test_inbound_route_bind_destination_fails_on_multiple_targets() -> None:
    route = InboundRoute.create(
        tenant_id=generate_id(EdiIdPrefix.TENANT),
        isa_sender_id="SENDER1",
        isa_receiver_id="RECEIVER1",
        webhook_id=generate_id(EdiIdPrefix.EDI_WEBHOOK),
    ).unwrap()
    _ = route.pull_domain_events()

    bind_res = route.bind_destination(
        webhook_id=generate_id(EdiIdPrefix.EDI_WEBHOOK),
        sftp_partner_id=generate_id(EdiIdPrefix.EDI_SFTP_PARTNER),
    )
    assert bind_res.is_err
    assert bind_res.unwrap_err().code == EdiErrorCode.INVALID_DESTINATION_MUTUAL_EXCLUSIVITY
    assert len(route.pull_domain_events()) == 0


def test_inbound_route_activation_deactivation_and_deletion_lifecycle() -> None:
    del_idem = generate_id(SystemIdPrefix.IDEMPOTENCY)
    route = InboundRoute.create(
        tenant_id=generate_id(EdiIdPrefix.TENANT),
        isa_sender_id="SENDER1",
        isa_receiver_id="RECEIVER1",
        webhook_id=generate_id(EdiIdPrefix.EDI_WEBHOOK),
    ).unwrap()
    _ = route.pull_domain_events()

    act_res = route.activate()
    assert act_res.is_ok
    assert route.active is True
    events = route.pull_domain_events()
    assert len(events) == 1
    assert isinstance(events[0], ProvisioningEvent)
    assert events[0].event_type == EdiEventType.edi_inbound_route_updated

    # Activating already active fails with first-class error
    act_dup = route.activate()
    assert act_dup.is_err
    assert act_dup.unwrap_err().code == EdiErrorCode.ROUTE_ALREADY_ACTIVE

    deact_res = route.deactivate()
    assert deact_res.is_ok
    assert route.active is False
    assert len(route.pull_domain_events()) == 1

    # Deactivating already inactive fails with first-class error
    deact_dup = route.deactivate()
    assert deact_dup.is_err
    assert deact_dup.unwrap_err().code == EdiErrorCode.ROUTE_ALREADY_INACTIVE

    del_res = route.mark_deleted(idempotency_key=del_idem)
    assert del_res.is_ok
    del_events = route.pull_domain_events()
    assert len(del_events) == 1
    assert isinstance(del_events[0], ProvisioningEvent)
    assert del_events[0].event_type == EdiEventType.edi_inbound_route_deleted
    assert del_events[0].idempotency_key == del_idem


def test_inbound_route_update_matching_criteria_and_atomic_update() -> None:
    webhook_id = generate_id(EdiIdPrefix.EDI_WEBHOOK)
    as2_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)
    trading_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)
    upd_idem = generate_id(SystemIdPrefix.IDEMPOTENCY)

    route = InboundRoute.create(
        tenant_id=generate_id(EdiIdPrefix.TENANT),
        isa_sender_id="OLD_SND",
        isa_receiver_id="OLD_RCV",
        webhook_id=webhook_id,
    ).unwrap()
    _ = route.pull_domain_events()

    # No-op update emits zero events
    noop_res = route.update(isa_sender_id="OLD_SND")
    assert noop_res.is_ok
    assert len(route.pull_domain_events()) == 0

    upd_res = route.update(
        isa_sender_id="NEW_SND",
        isa_receiver_id="NEW_RCV",
        gs_sender_id="GS_SND",
        gs_receiver_id="GS_RCV",
        transaction_type="855",
        processing_mode=ProcessingMode.PASSTHROUGH,
        name="Updated PO Ack",
        trading_partner_id=trading_partner_id,
        webhook_id=None,
        as2_partner_id=as2_partner_id,
        active=True,
        idempotency_key=upd_idem,
    )
    assert upd_res.is_ok
    assert route.isa_sender_id == "NEW_SND"
    assert route.isa_receiver_id == "NEW_RCV"
    assert route.gs_sender_id == "GS_SND"
    assert route.gs_receiver_id == "GS_RCV"
    assert route.transaction_type == "855"
    assert route.processing_mode == ProcessingMode.PASSTHROUGH
    assert route.name == "Updated PO Ack"
    assert route.trading_partner_id == trading_partner_id
    assert route.as2_partner_id == as2_partner_id
    assert route.webhook_id is None
    assert route.active is True

    # Must emit exactly ONE event with the supplied idempotency_key
    events = route.pull_domain_events()
    assert len(events) == 1
    assert isinstance(events[0], ProvisioningEvent)
    assert events[0].event_type == EdiEventType.edi_inbound_route_updated
    assert events[0].idempotency_key == upd_idem

    # Atomic failure leaves state untouched
    bad_upd = route.update(
        name="Should Not Apply",
        isa_sender_id="   ",
        webhook_id=UNSET,
    )
    assert bad_upd.is_err
    assert route.name == "Updated PO Ack"
    assert len(route.pull_domain_events()) == 0


def test_outbound_route_creation_and_destination_exclusivity() -> None:
    tenant_id = generate_id(EdiIdPrefix.TENANT)
    as2_target_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)

    result = OutboundRoute.create(
        tenant_id=tenant_id,
        name="Outbound Invoices",
        as2_partner_id=as2_target_id,
    )
    assert result.is_ok
    route = result.unwrap()
    assert route.id.startswith("edi_outb_rt_")
    assert route.as2_partner_id == as2_target_id
    assert route.connection_type == EdiConnectionType.AS2
    assert route.direction == EdiDirection.OUTBOUND
    assert route.active is False
    assert route.created_at.tzinfo is not None
    assert route.updated_at.tzinfo is not None
    assert route != replace(route)
    assert isinstance(hash(route), int)

    events = route.pull_domain_events()
    assert len(events) == 1
    assert isinstance(events[0], ProvisioningEvent)
    assert events[0].event_type == EdiEventType.edi_outbound_route_created

    # Multiple targets fail
    bad_res = OutboundRoute.create(
        tenant_id=tenant_id,
        as2_partner_id=generate_id(EdiIdPrefix.EDI_AS2_PARTNER),
        sftp_partner_id=generate_id(EdiIdPrefix.EDI_SFTP_PARTNER),
    )
    assert bad_res.is_err
    assert bad_res.unwrap_err().code == EdiErrorCode.INVALID_DESTINATION_MUTUAL_EXCLUSIVITY


def test_outbound_route_atomic_update_activation_and_deletion() -> None:
    as2_target_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)
    sftp_partner_id = generate_id(EdiIdPrefix.EDI_SFTP_PARTNER)
    trading_partner_id = generate_id(EdiIdPrefix.EDI_SFTP_PARTNER)
    upd_idem = generate_id(SystemIdPrefix.IDEMPOTENCY)
    del_idem = generate_id(SystemIdPrefix.IDEMPOTENCY)

    route = OutboundRoute.create(
        tenant_id=generate_id(EdiIdPrefix.TENANT),
        name="Initial Outbound",
        as2_partner_id=as2_target_id,
    ).unwrap()
    _ = route.pull_domain_events()

    # No-op update emits zero events
    noop_upd = route.update(name="Initial Outbound")
    assert noop_upd.is_ok
    assert len(route.pull_domain_events()) == 0

    # Rebind to SFTP + activate + rename in one atomic update
    upd = route.update(
        name="SFTP Invoices",
        trading_partner_id=trading_partner_id,
        as2_partner_id=None,
        sftp_partner_id=sftp_partner_id,
        active=True,
        idempotency_key=upd_idem,
    )
    assert upd.is_ok
    assert route.name == "SFTP Invoices"
    assert route.trading_partner_id == trading_partner_id
    assert route.as2_partner_id is None
    assert route.sftp_partner_id == sftp_partner_id
    assert route.connection_type == EdiConnectionType.SFTP
    assert route.active is True

    events = route.pull_domain_events()
    assert len(events) == 1
    assert isinstance(events[0], ProvisioningEvent)
    assert events[0].event_type == EdiEventType.edi_outbound_route_updated
    assert events[0].idempotency_key == upd_idem

    assert route.activate().is_err
    assert route.deactivate().is_ok
    assert route.active is False
    _ = route.pull_domain_events()

    del_res = route.mark_deleted(idempotency_key=del_idem)
    assert del_res.is_ok
    del_events = route.pull_domain_events()
    assert len(del_events) == 1
    assert isinstance(del_events[0], ProvisioningEvent)
    assert del_events[0].event_type == EdiEventType.edi_outbound_route_deleted


def test_route_destination_value_object_mutual_exclusivity() -> None:
    wh_id = generate_id(EdiIdPrefix.EDI_WEBHOOK)
    as2_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)
    sftp_id = generate_id(EdiIdPrefix.EDI_SFTP_PARTNER)

    wh_dest = RouteDestination.for_webhook(wh_id, "Webhook Target")
    assert wh_dest.target_id == wh_id
    assert wh_dest.connection_type == EdiConnectionType.WEBHOOK
    assert wh_dest.destination_name == "Webhook Target"

    as2_dest = RouteDestination.for_as2(as2_id)
    assert as2_dest.target_id == as2_id
    assert as2_dest.connection_type == EdiConnectionType.AS2

    sftp_dest = RouteDestination.for_sftp(sftp_id)
    assert sftp_dest.target_id == sftp_id
    assert sftp_dest.connection_type == EdiConnectionType.SFTP

    bad_res = RouteDestination.from_targets(webhook_id=wh_id, as2_partner_id=as2_id)
    assert bad_res.is_err
    assert bad_res.unwrap_err().code == EdiErrorCode.INVALID_DESTINATION_MUTUAL_EXCLUSIVITY


def test_route_binding_using_value_object() -> None:
    wh_init_id = generate_id(EdiIdPrefix.EDI_WEBHOOK)
    as2_dest_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)

    route = InboundRoute.create(
        tenant_id=generate_id(EdiIdPrefix.TENANT),
        isa_sender_id="SENDER1",
        isa_receiver_id="RECEIVER1",
        destination=RouteDestination.for_webhook(wh_init_id),
    ).unwrap()

    assert route.webhook_id == wh_init_id
    assert route.connection_type == EdiConnectionType.WEBHOOK

    new_dest = RouteDestination.for_as2(as2_dest_id, "Partner 88")
    rebind = route.bind_destination(new_dest)
    assert rebind.is_ok
    assert route.webhook_id is None
    assert route.as2_partner_id == as2_dest_id
    assert route.destination_name == "Partner 88"
    assert route.connection_type == EdiConnectionType.AS2


def test_outbound_edi_header_lifecycle() -> None:
    tenant_id = generate_id(EdiIdPrefix.TENANT)
    trading_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)

    bad_res = OutboundEdiHeader.create(
        tenant_id=tenant_id,
        trading_partner_id="",
        isa_sender_id="SND",
        isa_receiver_id="RCV",
    )
    assert bad_res.is_err
    assert bad_res.unwrap_err().code == EdiErrorCode.INVALID_MATCHING_CRITERIA

    res = OutboundEdiHeader.create(
        tenant_id=tenant_id,
        trading_partner_id=trading_partner_id,
        isa_sender_id="SND01",
        isa_receiver_id="RCV01",
        transaction_type="810",
        default_standard="X12",
        default_version="004010",
    )
    assert res.is_ok
    header = res.unwrap()
    assert header.id.startswith("edi_outb_hdr_")
    assert header.created_at.tzinfo is not None
    assert header.updated_at.tzinfo is not None
    assert header != replace(header)
    assert isinstance(hash(header), int)
    events = header.pull_domain_events()
    assert len(events) == 1
    assert isinstance(events[0], ProvisioningEvent)
    assert events[0].event_type == EdiEventType.edi_header_created

    # No-op update emits zero events
    noop_upd = header.update(isa_sender_id="SND01")
    assert noop_upd.is_ok
    assert len(header.pull_domain_events()) == 0

    upd_bad = header.update(isa_sender_id="  ")
    assert upd_bad.is_err
    assert header.isa_sender_id == "SND01"

    upd_ok = header.update(name="Acme 810 Header", gs_sender_id="GS01")
    assert upd_ok.is_ok
    assert header.name == "Acme 810 Header"
    assert header.gs_sender_id == "GS01"
    upd_events = header.pull_domain_events()
    assert len(upd_events) == 1
    assert isinstance(upd_events[0], ProvisioningEvent)
    assert upd_events[0].event_type == EdiEventType.edi_header_updated

    envelope = header.to_envelope_headers(fallback_transaction_type="850")
    assert isinstance(envelope, EdiEnvelopeHeaders)
    assert envelope.isa_sender_id == "SND01"
    assert envelope.transaction_type == "810"

    del_res = header.mark_deleted()
    assert del_res.is_ok
    del_events = header.pull_domain_events()
    assert len(del_events) == 1
    assert isinstance(del_events[0], ProvisioningEvent)
    assert del_events[0].event_type == EdiEventType.edi_header_deleted


def test_webhook_readonly_value_object() -> None:
    now = datetime.now(UTC)
    wh_id = generate_id(EdiIdPrefix.EDI_WEBHOOK)
    tenant_id = generate_id(EdiIdPrefix.TENANT)

    wh = Webhook(
        id=wh_id,
        tenant_id=tenant_id,
        name="ERP Webhook",
        url="https://erp.example.com/edi",
        active=True,
        created_at=now,
        updated_at=now,
        auth_header_vault_ref="vault://webhooks/erp",
    )
    assert wh.id == wh_id
    assert wh.tenant_id == tenant_id
    assert wh.active is True
    assert wh == Webhook(
        id=wh_id,
        tenant_id=tenant_id,
        name="ERP Webhook",
        url="https://erp.example.com/edi",
        active=True,
        created_at=now,
        updated_at=now,
        auth_header_vault_ref="vault://webhooks/erp",
    )

    attr_name = "name"
    with pytest.raises(FrozenInstanceError):
        setattr(wh, attr_name, "Mutated")
