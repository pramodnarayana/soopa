import datetime
import functools

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from seedwork import generate_id
from sqlalchemy import select

from edi.adapters.inbound.as2.builder import build_outbound_message
from edi.adapters.outbound.database.models.control_plane import (
    AS2Partner,
    AS2Partnership,
    InboundRoute,
)
from edi.adapters.outbound.database.models.data_plane import (
    EdiMessage,
    Webhook,
)
from edi.adapters.outbound.database.models.data_plane import (
    InboundRoute as DataPlaneInboundRoute,
)
from edi.adapters.outbound.security.smime import encrypt_payload, sign_payload

EDI_PAYLOAD = b"ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *210101*1200*U*00401*000000001*0*T*:~GS*PO*SENDER*RECEIVER*20210101*1200*1*X*004010~ST*850*0001~BEG*00*NE*456**20210101~SE*3*0001~GE*1*1~IEA*1*000000001~"


def generate_self_signed_cert() -> tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "test_cert"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC).replace(tzinfo=None))
        .not_valid_after(
            datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + datetime.timedelta(days=10)
        )
        .sign(private_key, hashes.SHA256())
    )

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    return private_bytes, cert_bytes


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inbound_as2_crypto_integration(
    db_session, tenant_db_session, client: httpx.AsyncClient, override_get_secret_store
) -> None:
    """
    Tests the ProcessInboundAs2MessageUseCase full crypto pipeline.
    Sends a fully Enveloped (Signed & Encrypted) AS2 HTTP Request and validates
    that it is properly decrypted, signature verified, and the raw EDI is saved.
    """
    tenant_id = "test-tenant"

    # Create Local and Remote AS2 Partners for validation
    local_priv, local_cert = generate_self_signed_cert()
    remote_priv, remote_cert = generate_self_signed_cert()

    # Seed the fake vault with our certificates and keys
    override_get_secret_store.secrets["mock/tenant/local_priv"] = local_priv.decode("utf-8")
    override_get_secret_store.secrets["mock/tenant/local_cert"] = local_cert.decode("utf-8")
    override_get_secret_store.secrets["mock/tenant/remote_cert"] = remote_cert.decode("utf-8")

    # Using db_session for Control Plane partnerships
    local_partner = AS2Partner(
        tenant_id=tenant_id,
        name="Local",
        as2_id="RECEIVER",
        is_local=True,
        active=True,
        private_key_vault_ref="mock/tenant/local_priv",
        public_cert_vault_ref="mock/tenant/local_cert",
    )
    remote_partner = AS2Partner(
        tenant_id=tenant_id,
        name="Remote",
        as2_id="SENDER",
        is_local=False,
        active=True,
        public_cert_vault_ref="mock/tenant/remote_cert",
    )
    db_session.add_all([local_partner, remote_partner])
    await db_session.flush()

    partnership = AS2Partnership(
        tenant_id=tenant_id,
        name="Test Partnership",
        local_partner_id=local_partner.id,
        remote_partner_id=remote_partner.id,
        active=True,
        encryption_algorithm="AES256",
        signature_algorithm="SHA256",
    )
    db_session.add(partnership)
    await db_session.commit()

    # Create InboundRoute in Control Plane (Global DB) for Tenant Resolution
    webhook_id = generate_id("wh")
    inbound_route = InboundRoute(
        tenant_id=tenant_id,
        name="Test Route",
        isa_sender_id="SENDER",
        isa_receiver_id="RECEIVER",
        transaction_type="850",
        webhook_id=webhook_id,
        active=True,
    )
    db_session.add(inbound_route)
    await db_session.commit()

    t_webhook = Webhook(
        id=webhook_id,
        tenant_id=tenant_id,
        name="Crypto Test Webhook",
        url="http://127.0.0.1:9999/webhook",
        active=True,
    )
    tenant_db_session.add(t_webhook)
    await tenant_db_session.flush()

    t_route = DataPlaneInboundRoute(
        tenant_id=tenant_id,
        name="Test Route",
        isa_sender_id="SENDER",
        isa_receiver_id="RECEIVER",
        transaction_type="850",
        webhook_id=webhook_id,
        active=True,
    )
    tenant_db_session.add(t_route)
    await tenant_db_session.commit()

    # Create closures for building the payload
    sign_fn = functools.partial(
        sign_payload, private_key_pem=remote_priv, public_cert_pem=remote_cert
    )
    # The message is encrypted USING the receiver's (local) public certificate
    encrypt_fn = functools.partial(encrypt_payload, public_cert_pem=local_cert, algorithm="AES256")

    # Build FULLY encrypted and signed AS2 payload
    msg = build_outbound_message(
        payload=EDI_PAYLOAD,
        as2_from="SENDER",
        as2_to="RECEIVER",
        sign_fn=sign_fn,
        encrypt_fn=encrypt_fn,
    )

    # (AsyncMock for FakeVault removed in favor of direct seeding)
    # Send to API AS2 server
    response = await client.post(
        "/api/v1/as2/receive",
        content=msg.body,
        headers=msg.headers,
    )

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. Text: {response.text}"
    )

    # Verify Data Plane: The pure EDI payload must be saved!

    res = await tenant_db_session.execute(
        select(EdiMessage).where(EdiMessage.as2_sender_id == "SENDER")
    )
    edi_msg = res.scalar_one()

    # The payload is stored in the DB as string, but originally bytes. Let's compare strings.
    assert edi_msg.edi_data == EDI_PAYLOAD.decode("utf-8")
