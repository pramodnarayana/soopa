import os
from datetime import UTC, datetime

import pytest

from edi.application.use_cases.inbound_routes.create_inbound_route_use_case import (
    CreateInboundRouteCmd,
)
from edi.application.use_cases.inbound_routes.update_inbound_route_use_case import (
    UpdateInboundRouteCmd,
)
from edi.application.use_cases.outbound_routes.create_outbound_route_use_case import (
    CreateOutboundRouteCmd,
)
from edi.application.use_cases.outbound_routes.update_outbound_route_use_case import (
    UpdateOutboundRouteCmd,
)
from edi.application.use_cases.sftp_partners.create_sftp_partner_use_case import (
    CreateSFTPPartnerCmd,
)
from edi.application.use_cases.sftp_partners.update_sftp_partner_use_case import (
    UpdateSFTPPartnerCmd,
    UpdateSFTPPartnerUseCase,
)
from edi.domain.partner.as2.partner import AS2Partner
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.testing.fakes.api_fakes import FakeControlPlaneUnitOfWork


def make_as2_partner(partner_id: str, as2_id: str, tenant_id: str = "tenant-1") -> AS2Partner:
    now = datetime.now(UTC)
    return AS2Partner(
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
    uow = FakeControlPlaneUnitOfWork()
    inbound_id = await uow.inbound_routes.create_inbound_route(
        "tenant-1",
        CreateInboundRouteCmd(
            isa_sender_id="sender",
            isa_receiver_id="receiver",
            transaction_type="850",
        ),
    )
    outbound_id = await uow.outbound_routes.create_outbound_route(
        "tenant-1",
        CreateOutboundRouteCmd(
            isa_sender_id="sender",
            isa_receiver_id="receiver",
            transaction_type="850",
        ),
    )

    assert not await uow.inbound_routes.update_inbound_route(
        "tenant-2", inbound_id, UpdateInboundRouteCmd(name="changed")
    )
    assert not await uow.inbound_routes.delete_inbound_route("tenant-2", inbound_id)
    assert not await uow.outbound_routes.update_outbound_route(
        "tenant-2", outbound_id, UpdateOutboundRouteCmd(name="changed")
    )
    assert not await uow.outbound_routes.delete_outbound_route("tenant-2", outbound_id)
    assert inbound_id in uow.inbound_routes.inbound_routes
    assert outbound_id in uow.outbound_routes.outbound_routes


@pytest.mark.asyncio
async def test_save_serializes_and_clears_aggregate_domain_events():
    uow = FakeControlPlaneUnitOfWork()
    partner = make_as2_partner("local-id", "LOCAL")
    partner.update(name="LOCAL_UPDATED", idempotency_key="request-1")

    await uow.as2_partners.save(partner)

    assert partner.domain_events == []
    assert len(uow.as2_partners.outbox.outbox_events) == 1
    event = uow.as2_partners.outbox.outbox_events[0]
    assert event.tenant_id == "tenant-1"
    assert event.event_type == "edi.as2_partner.updated"
    assert event.idempotency_key == "request-1"
    assert event.payload == {
        "idempotency_key": "request-1",
        "tenant_id": "tenant-1",
        "event_type": "edi.as2_partner.updated",
        "resource_id": "local-id",
    }


@pytest.mark.asyncio
async def test_get_partnership_by_as2_ids_resolves_partners_and_partnership():
    uow = FakeControlPlaneUnitOfWork()
    local = make_as2_partner("local-id", "LOCAL")
    remote = make_as2_partner("remote-id", "REMOTE")
    now = datetime.now(UTC)
    partnership = AS2Partnership(
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
    await uow.as2_partners.save(local)
    await uow.as2_partners.save(remote)
    await uow.as2_partnerships.save(partnership)

    result = await uow.as2_partnerships.get_partnership_by_as2_ids("remote", "local")

    assert result == (partnership, local, remote)


@pytest.mark.asyncio
async def test_get_partnership_by_as2_ids_rejects_cross_tenant_partners():
    uow = FakeControlPlaneUnitOfWork()
    local = make_as2_partner("local-id", "LOCAL", tenant_id="tenant-1")
    remote = make_as2_partner("remote-id", "REMOTE", tenant_id="tenant-2")
    now = datetime.now(UTC)
    partnership = AS2Partnership(
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
    await uow.as2_partners.save(local)
    await uow.as2_partners.save(remote)
    await uow.as2_partnerships.save(partnership)

    assert await uow.as2_partnerships.get_partnership_by_as2_ids("remote", "local") is None


class FakeFieldEncryption:
    def encrypt_str(self, text: str) -> str:
        return f"encrypted:{text}"

    def decrypt_str(self, ciphertext: str) -> str:
        if ciphertext.startswith("encrypted:"):
            return ciphertext[10:]
        return ciphertext

    def encrypt_dict(self, data: dict[str, object]) -> bytes:
        return b"{}"

    def decrypt_dict(self, encrypted_bytes: bytes) -> dict[str, object]:
        return {}


@pytest.mark.asyncio
async def test_update_sftp_password_maps_to_encrypted_field():
    uow = FakeControlPlaneUnitOfWork()
    partner_id = await uow.sftp_partners.create_sftp_partner(
        "tenant-1",
        CreateSFTPPartnerCmd(name="SFTP", host="sftp.example.com", username="user"),
    )
    use_case = UpdateSFTPPartnerUseCase(
        uow=uow,
        field_encryption=FakeFieldEncryption(),
    )

    res = await use_case.update_sftp_partner(
        "tenant-1",
        partner_id,
        UpdateSFTPPartnerCmd(password=os.environ.get("DUMMY_PASSWORD", "secret")),
    )
    assert res.is_ok
    partner = res.unwrap()

    assert partner.password_encrypted == f"encrypted:{os.environ.get('DUMMY_PASSWORD', 'secret')}"
    assert "password" not in type(partner).__dataclass_fields__


@pytest.mark.asyncio
async def test_save_finalizes_idempotency_reservation_in_fake_outbox() -> None:
    uow = FakeControlPlaneUnitOfWork()
    await uow.control_plane_outbox.create_reservation(
        tenant_id="tenant-1",
        idempotency_key="idem-42",
        fingerprint="fp-abc",
    )
    partner = AS2Partner.create(
        tenant_id="tenant-1",
        name="Remote Partner",
        as2_id="REMOTE_42",
        is_local=False,
        url="https://remote.example.com/as2",
        public_cert_pem="-----BEGIN CERTIFICATE-----\ncert\n-----END CERTIFICATE-----",
        idempotency_key="idem-42",
    ).unwrap()

    await uow.as2_partners.save(partner)

    finalized = await uow.control_plane_outbox.get_event_by_idempotency_key("idem-42")
    assert finalized is not None
    assert finalized.id == "reservation_idem-42"
    assert finalized.event_type == "edi.as2_partner.created"
    assert finalized.payload == {
        "fingerprint": "fp-abc",
        "idempotency_key": "idem-42",
        "tenant_id": "tenant-1",
        "event_type": "edi.as2_partner.created",
        "resource_id": partner.id,
    }
