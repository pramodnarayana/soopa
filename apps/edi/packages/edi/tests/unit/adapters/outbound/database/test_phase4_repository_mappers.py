"""Pure zero-mock Phase 4 unit tests for EDI SQLAlchemy Data Mappers and reflection-free test fakes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from database.models.identity import Tenant as OrmTenant
from identity.domain.constants import IdentityIdPrefix
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from ucp.domain.constants import LifecycleStatus, UcpIdPrefix

from edi.adapters.outbound.database.control_plane.as2_partnership_repository import (
    SqlAlchemyAS2PartnershipRepository,
)
from edi.adapters.outbound.database.control_plane.edi_header_repository import (
    SqlAlchemyEdiHeaderRepository,
)
from edi.adapters.outbound.database.control_plane.inbound_route_repository import (
    SqlAlchemyInboundRouteRepository,
)
from edi.adapters.outbound.database.control_plane.tenant_repository import (
    SqlAlchemyTenantRepository,
)
from edi.adapters.outbound.database.data_plane.api_gateway_repository import (
    SqlAlchemyApiGatewayRepository,
)
from edi.adapters.outbound.database.data_plane.edi_json_repository import (
    SqlAlchemyEdiJsonRepository,
)
from edi.adapters.outbound.database.data_plane.edi_message_repository import (
    SqlAlchemyEdiMessageRepository,
)
from edi.adapters.outbound.database.models.control_plane import (
    AS2Partner as OrmAS2Partner,
)
from edi.adapters.outbound.database.models.control_plane import (
    AS2Partnership as OrmAS2Partnership,
)
from edi.adapters.outbound.database.models.control_plane import (
    InboundRoute as OrmInboundRoute,
)
from edi.adapters.outbound.database.models.control_plane import (
    OutboundEdiHeader as OrmOutboundEdiHeader,
)
from edi.adapters.outbound.database.models.data_plane import (
    ApiGateway as OrmApiGateway,
)
from edi.adapters.outbound.database.models.data_plane import (
    EdiJson as OrmEdiJson,
)
from edi.adapters.outbound.database.models.data_plane import (
    EdiMessage as OrmEdiMessage,
)
from edi.domain.constants import EdiIdPrefix
from edi.domain.routing.enums import Direction, EdiConnectionType, ProcessingMode
from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import MessageStatus, RecordStatus
from edi.domain.transaction.gateway_receipt import ApiGatewayReceipt
from edi.testing.fakes.pipeline_fakes import InMemoryRepositoryAdapter


def test_inbound_route_mapper_maps_all_explicit_fields() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    route_id = generate_id(EdiIdPrefix.EDI_INBOUND_ROUTE.value)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    trading_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)
    webhook_id = generate_id(UcpIdPrefix.WEBHOOK.value)

    record = OrmInboundRoute(
        id=route_id,
        tenant_id=tenant_id,
        name="Inbound 850",
        isa_sender_id="PARTNER",
        isa_receiver_id="ACME",
        active=True,
        created_at=now,
        updated_at=now,
        trading_partner_id=trading_partner_id,
        gs_sender_id="GS_PARTNER",
        gs_receiver_id="GS_ACME",
        transaction_type="850",
        processing_mode=ProcessingMode.TRANSFORM.value,
        webhook_id=webhook_id,
        as2_partner_id=None,
        sftp_partner_id=None,
        connection_type=EdiConnectionType.API.value,
    )

    domain_model = SqlAlchemyInboundRouteRepository._to_domain_model(record)
    assert domain_model.id == route_id
    assert domain_model.tenant_id == tenant_id
    assert domain_model.trading_partner_id == trading_partner_id
    assert domain_model.webhook_id == webhook_id
    assert domain_model.processing_mode == ProcessingMode.TRANSFORM
    assert domain_model.connection_type == EdiConnectionType.API


def test_edi_header_as2_partnership_and_tenant_mappers() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    header_id = generate_id(EdiIdPrefix.EDI_OUTBOUND_HEADER.value)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    trading_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)

    header_orm = OrmOutboundEdiHeader(
        id=header_id,
        tenant_id=tenant_id,
        trading_partner_id=trading_partner_id,
        isa_sender_id="ACME",
        isa_receiver_id="PARTNER",
        created_at=now,
        updated_at=now,
        name="Default Header",
        isa_sender_qualifier="ZZ",
        isa_receiver_qualifier="01",
        gs_sender_id="GS_ACME",
        gs_receiver_id="GS_PARTNER",
        transaction_type="810",
        default_standard="X12",
        default_version="004010",
    )
    header = SqlAlchemyEdiHeaderRepository._to_domain_model(header_orm)
    assert header.id == header_id
    assert header.trading_partner_id == trading_partner_id
    assert header.default_standard == "X12"
    assert header.default_version == "004010"

    partnership_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNERSHIP.value)
    local_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)
    remote_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)

    partnership_orm = OrmAS2Partnership(
        id=partnership_id,
        tenant_id=PLATFORM_TENANT_ID,
        name="ACME <-> Walmart",
        local_partner_id=local_partner_id,
        remote_partner_id=remote_partner_id,
        mdn_type="SYNC",
        encryption_algorithm="aes256_cbc",
        signature_algorithm="sha256",
        created_at=now,
        updated_at=now,
        credentials_vault_ref=None,
        mdn_url=None,
        advanced_flags={"compress": True},
        active=True,
    )
    partnership = SqlAlchemyAS2PartnershipRepository._to_domain_model(partnership_orm)
    assert partnership.id == partnership_id
    assert partnership.local_partner_id == local_partner_id
    assert partnership.remote_partner_id == remote_partner_id
    assert partnership.advanced_flags == {"compress": True}

    partner_orm = OrmAS2Partner(
        id=local_partner_id,
        tenant_id=PLATFORM_TENANT_ID,
        as2_id="ACME_AS2",
        name="ACME Local",
        is_local=True,
        created_at=now,
        updated_at=now,
        active=True,
    )
    partner = SqlAlchemyAS2PartnershipRepository._to_partner_domain_model(partner_orm)
    assert partner.id == local_partner_id
    assert partner.as2_id == "ACME_AS2"

    idp_org_id = generate_id(SystemIdPrefix.GENERIC.value)
    tenant_orm = OrmTenant(
        id=tenant_id,
        idp_tenant_id=idp_org_id,
        name="Acme Corp",
        slug="acme-corp",
        status=LifecycleStatus.ACTIVE.value,
        created_at=now,
        updated_at=now,
    )
    tenant_summary = SqlAlchemyTenantRepository._to_domain_model(tenant_orm)
    assert tenant_summary.id == tenant_id
    assert tenant_summary.idp_tenant_id == idp_org_id
    assert tenant_summary.name == "Acme Corp"


def test_data_plane_stage_repository_bidirectional_mappers() -> None:
    now = datetime.now(UTC)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    trace_id = generate_id(SystemIdPrefix.TRACE.value)
    parent_trace_id = generate_id(SystemIdPrefix.TRACE.value)
    original_trace_id = generate_id(SystemIdPrefix.TRACE.value)
    partner_1 = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)
    partner_2 = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)
    json_id = generate_id(EdiIdPrefix.EDI_JSON.value)

    json_agg = EdiJson(
        id=json_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        direction=Direction.INBOUND,
        status=MessageStatus.RECEIVED,
        created_at=now,
        updated_at=now,
        trading_partner_id=partner_1,
        transaction_type="850",
        standard="X12",
        business_metadata={"po": "PO-100"},
        payload={"po_number": "PO-100"},
    )
    orm_json: OrmEdiJson = SqlAlchemyEdiJsonRepository._to_orm_record(json_agg)
    assert orm_json.id == json_id
    assert orm_json.status == MessageStatus.RECEIVED.value

    json_agg.mark_transformed()
    json_agg.payload = {"po_number": "PO-100", "normalized": True}
    json_agg.trading_partner_id = partner_2
    json_agg.standard = "EDIFACT"
    json_agg.status_message = "Transformed cleanly"
    json_agg.error_code = "ERR_NONE"
    json_agg.error_details = {"detail": "none"}
    json_agg.storage_uri = "s3://edi-payloads/json/po-100.json"
    json_agg.replay_count = 2
    json_agg.parent_trace_id = parent_trace_id
    json_agg.original_trace_id = original_trace_id
    SqlAlchemyEdiJsonRepository._update_record_from_domain(orm_json, json_agg)

    round_tripped_json = SqlAlchemyEdiJsonRepository._to_domain_model(orm_json)
    assert round_tripped_json.status == MessageStatus.TRANSFORMED
    assert round_tripped_json.trading_partner_id == partner_2
    assert round_tripped_json.standard == "EDIFACT"
    assert round_tripped_json.status_message == "Transformed cleanly"
    assert round_tripped_json.error_code == "ERR_NONE"
    assert round_tripped_json.error_details == {"detail": "none"}
    assert round_tripped_json.storage_uri == "s3://edi-payloads/json/po-100.json"
    assert round_tripped_json.replay_count == 2
    assert round_tripped_json.parent_trace_id == parent_trace_id
    assert round_tripped_json.original_trace_id == original_trace_id

    msg_id = generate_id(EdiIdPrefix.EDI_MESSAGE.value)
    msg_agg = EdiMessage.create_outbound(
        id=msg_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        edi_data="ISA*00*...",
        format_standard="X12",
        transaction_type="850",
        sender_id="ACME",
        receiver_id="PARTNER",
        gs_sender_id="GS_ACME",
        gs_receiver_id="GS_PARTNER",
        trading_partner_id=partner_1,
    )
    orm_msg: OrmEdiMessage = SqlAlchemyEdiMessageRepository._to_orm_record(msg_agg)
    msg_agg.status = RecordStatus.DELIVERED
    msg_agg.mdn_id = "<mdn-100@partner.test>"
    msg_agg.mdn_mode = "SYNC"
    msg_agg.replay_count = 1
    msg_agg.storage_uri = "s3://edi-payloads/raw/850.edi"
    SqlAlchemyEdiMessageRepository._update_record_from_domain(orm_msg, msg_agg)

    round_tripped_msg = SqlAlchemyEdiMessageRepository._to_domain_model(orm_msg)
    assert round_tripped_msg.id == msg_id
    assert round_tripped_msg.sender_id == "ACME"
    assert round_tripped_msg.status == RecordStatus.DELIVERED
    assert round_tripped_msg.mdn_id == "<mdn-100@partner.test>"
    assert round_tripped_msg.mdn_mode == "SYNC"
    assert round_tripped_msg.replay_count == 1
    assert round_tripped_msg.storage_uri == "s3://edi-payloads/raw/850.edi"

    gw_id = generate_id(EdiIdPrefix.EDI_API_GATEWAY.value)
    gw_receipt = ApiGatewayReceipt(
        id=gw_id,
        tenant_id=tenant_id,
        trace_id=trace_id,
        direction=Direction.INBOUND,
        status=MessageStatus.PENDING_DELIVERY,
        created_at=now,
        updated_at=now,
        transaction_type="850",
        webhook_url="https://erp.example.com/edi",
        http_status_code=None,
        payload={"ok": True},
    )
    orm_gw: OrmApiGateway = SqlAlchemyApiGatewayRepository._to_orm_record(gw_receipt)
    gw_receipt.status = MessageStatus.DELIVERED
    gw_receipt.http_status_code = 200
    gw_receipt.response = '{"accepted":true}'
    gw_receipt.replay_count = 1
    SqlAlchemyApiGatewayRepository._update_record_from_domain(orm_gw, gw_receipt)

    round_tripped_gw = SqlAlchemyApiGatewayRepository._to_domain_model(orm_gw)
    assert round_tripped_gw.id == gw_id
    assert round_tripped_gw.status == MessageStatus.DELIVERED
    assert round_tripped_gw.http_status_code == 200
    assert round_tripped_gw.response == '{"accepted":true}'
    assert round_tripped_gw.replay_count == 1


@pytest.mark.asyncio
async def test_in_memory_pipeline_repository_adapter_typed_mappers() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)
    header_id = generate_id(EdiIdPrefix.EDI_OUTBOUND_HEADER.value)
    sftp_id = generate_id(EdiIdPrefix.EDI_SFTP_PARTNER.value)
    webhook_id = generate_id(EdiIdPrefix.EDI_WEBHOOK.value)
    as2_remote_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)
    as2_local_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)
    as2_pship_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNERSHIP.value)
    trace_id = generate_id(SystemIdPrefix.TRACE.value)
    msg_id = generate_id(EdiIdPrefix.EDI_MESSAGE.value)

    repo = InMemoryRepositoryAdapter()
    repo.outbound_edi_headers[partner_id] = {
        "id": header_id,
        "tenant_id": tenant_id,
        "trading_partner_id": partner_id,
        "isa_sender_id": "SENDER",
        "isa_receiver_id": "RECEIVER",
        "default_standard": "X12",
    }
    repo.sftp_partners[sftp_id] = {
        "id": sftp_id,
        "tenant_id": tenant_id,
        "name": "Partner SFTP",
        "host": "sftp.partner.test",
        "port": 2222,
        "username": "edi_user",
        "active": True,
        "credentials_vault_ref": "vault://sftp/partner",
    }
    repo.webhooks[webhook_id] = {
        "id": webhook_id,
        "tenant_id": tenant_id,
        "name": "ERP Webhook",
        "url": "https://erp.partner.test/hook",
        "active": True,
    }
    repo.as2_partners[as2_remote_id] = {
        "remote": {
            "id": as2_remote_id,
            "tenant_id": tenant_id,
            "as2_id": "PARTNER_AS2",
            "name": "Partner AS2",
            "is_local": False,
            "url": "https://as2.partner.test/as2",
            "active": True,
        },
        "partnership": {
            "id": as2_pship_id,
            "tenant_id": PLATFORM_TENANT_ID,
            "name": "Bilateral AS2",
            "local_partner_id": as2_local_id,
            "remote_partner_id": as2_remote_id,
            "mdn_type": "SYNC",
            "encryption_algorithm": "aes256_cbc",
            "signature_algorithm": "sha256",
            "active": True,
        },
    }

    header = await repo.get_outbound_edi_header_by_trading_partner_id(partner_id, tenant_id)
    assert header is not None
    assert header.default_standard == "X12"

    sftp = await repo.get_sftp_partner(tenant_id, sftp_id)
    assert sftp is not None
    assert sftp.port == 2222

    webhook = await repo.get_webhook(tenant_id, webhook_id)
    assert webhook is not None
    assert webhook.url == "https://erp.partner.test/hook"

    as2_partner = await repo.get_as2_partner(tenant_id, as2_remote_id)
    assert as2_partner is not None
    assert as2_partner.as2_id == "PARTNER_AS2"

    as2_partnership = await repo.get_as2_partnership(tenant_id, as2_pship_id)
    assert as2_partnership is not None
    assert as2_partnership.remote_partner_id == as2_remote_id

    inbound_msg = EdiMessage.create_inbound(
        id=msg_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        edi_data="ISA*00*...",
        status=MessageStatus.RECEIVED.value,
        trading_partner_id=partner_id,
        sender_id="PARTNER",
        receiver_id="ACME",
        connection_type="AS2",
    )
    await repo.save(inbound_msg)
    loaded_msg = await repo.get_edi_message(trace_id, tenant_id)
    assert loaded_msg is not None
    assert loaded_msg.sender_id == "PARTNER"
    assert len(repo.outbox) == 1
