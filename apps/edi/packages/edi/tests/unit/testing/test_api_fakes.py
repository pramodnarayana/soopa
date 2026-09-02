from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from edi.application.dto import (
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    UpdateInboundRouteCmd,
    UpdateOutboundRouteCmd,
    UpdateSFTPPartnerCmd,
)
from edi.application.use_cases.sftp_partners.update_sftp_partner_use_case import (
    UpdateSFTPPartnerUseCase,
)
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models.as2 import AS2PartnerDomainModel, AS2PartnershipDomainModel
from edi.testing.fakes.api_fakes import FakeGlobalStore


def make_as2_partner(
    partner_id: str, as2_id: str, tenant_id: str = "tenant-1"
) -> AS2PartnerDomainModel:
    now = datetime.now(UTC)
    return AS2PartnerDomainModel(
        id=partner_id,
        tenant_id=tenant_id,
        as2_id=as2_id,
        name=as2_id,
        is_local=as2_id == "LOCAL",
        active=True,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_route_mutations_reject_a_different_tenant():
    store = FakeGlobalStore()
    inbound_id = await store.create_inbound_route(
        "tenant-1",
        CreateInboundRouteCmd(
            isa_sender_id="sender",
            isa_receiver_id="receiver",
            transaction_type="850",
        ),
    )
    outbound_id = await store.create_outbound_route(
        "tenant-1",
        CreateOutboundRouteCmd(
            isa_sender_id="sender",
            isa_receiver_id="receiver",
            transaction_type="850",
        ),
    )

    assert not await store.update_inbound_route(
        "tenant-2", inbound_id, UpdateInboundRouteCmd(name="changed")
    )
    assert not await store.delete_inbound_route("tenant-2", inbound_id)
    assert not await store.update_outbound_route(
        "tenant-2", outbound_id, UpdateOutboundRouteCmd(name="changed")
    )
    assert not await store.delete_outbound_route("tenant-2", outbound_id)
    assert inbound_id in store.inbound_routes
    assert outbound_id in store.outbound_routes


@pytest.mark.asyncio
async def test_save_serializes_and_clears_aggregate_domain_events():
    store = FakeGlobalStore()
    partner = make_as2_partner("local-id", "LOCAL")
    partner.add_domain_event(
        ProvisioningEvent(
            tenant_id="tenant-1",
            event_type=EdiEventType.edi_as2_partner_updated,
            resource_id=partner.id,
            explicit_idempotency_key="request-1",
        )
    )

    await store.save(partner)

    assert partner.domain_events == []
    assert store.outbox_events == [
        {
            "tenant_id": "tenant-1",
            "event_type": "edi.as2_partner.updated",
            "payload": {
                "explicit_idempotency_key": "request-1",
                "tenant_id": "tenant-1",
                "event_type": "edi.as2_partner.updated",
                "resource_id": "local-id",
            },
            "idempotency_key": "request-1",
        }
    ]


@pytest.mark.asyncio
async def test_get_partnership_by_as2_ids_resolves_partners_and_partnership():
    store = FakeGlobalStore()
    local = make_as2_partner("local-id", "LOCAL")
    remote = make_as2_partner("remote-id", "REMOTE")
    now = datetime.now(UTC)
    partnership = AS2PartnershipDomainModel(
        id="partnership-id",
        tenant_id="tenant-1",
        name="partnership",
        local_partner_id=local.id,
        remote_partner_id=remote.id,
        mdn_type="SYNC",
        encryption_algorithm="AES256",
        signature_algorithm="SHA256",
        active=True,
        created_at=now,
        updated_at=now,
    )
    await store.save(local)
    await store.save(remote)
    await store.save(partnership)

    result = await store.get_partnership_by_as2_ids("remote", "local")

    assert result == (partnership, local, remote)


@pytest.mark.asyncio
async def test_get_partnership_by_as2_ids_rejects_cross_tenant_partners():
    store = FakeGlobalStore()
    local = make_as2_partner("local-id", "LOCAL", tenant_id="tenant-1")
    remote = make_as2_partner("remote-id", "REMOTE", tenant_id="tenant-2")
    now = datetime.now(UTC)
    partnership = AS2PartnershipDomainModel(
        id="partnership-id",
        tenant_id="tenant-1",
        name="partnership",
        local_partner_id=local.id,
        remote_partner_id=remote.id,
        mdn_type="SYNC",
        encryption_algorithm="AES256",
        signature_algorithm="SHA256",
        active=True,
        created_at=now,
        updated_at=now,
    )
    await store.save(local)
    await store.save(remote)
    await store.save(partnership)

    assert await store.get_partnership_by_as2_ids("remote", "local") is None


class FakeFieldEncryption:
    def encrypt(self, data: str) -> str:
        return f"encrypted:{data}"


@pytest.mark.asyncio
async def test_update_sftp_password_maps_to_encrypted_field():
    store = FakeGlobalStore()
    partner_id = await store.create_sftp_partner(
        "tenant-1",
        CreateSFTPPartnerCmd(name="SFTP", host="sftp.example.com", username="user"),
    )
    use_case = UpdateSFTPPartnerUseCase(
        uow=SimpleNamespace(sftp_partners=store),
        field_encryption=FakeFieldEncryption(),
    )

    partner = await use_case.update_sftp_partner(
        "tenant-1",
        partner_id,
        UpdateSFTPPartnerCmd(password="secret"),  # noqa: S106
    )

    assert partner.password_encrypted == "encrypted:secret"  # noqa: S105
    assert not hasattr(partner, "password")
