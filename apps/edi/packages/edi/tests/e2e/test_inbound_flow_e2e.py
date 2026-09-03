import base64
import contextlib
import datetime
from unittest.mock import MagicMock

import httpx
import pytest
import structlog
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from database.models import Webhook as GlobalWebhook
from seedwork import generate_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.inbound.as2.builder import build_outbound_message
from edi.adapters.outbound.database.data_plane_unit_of_work import SqlAlchemyDataPlaneUnitOfWork
from edi.adapters.outbound.database.models.control_plane import (
    AS2Partner,
    AS2Partnership,
)
from edi.adapters.outbound.database.models.control_plane import (
    InboundRoute as ControlPlaneInboundRoute,
)
from edi.adapters.outbound.database.models.data_plane import (
    EdiMessage,
)
from edi.adapters.outbound.database.models.data_plane import (
    InboundRoute as DataPlaneInboundRoute,
)
from edi.adapters.outbound.database.models.data_plane import (
    Webhook as DataPlaneWebhook,
)
from edi.adapters.outbound.pipeline.storage import S3StorageClient
from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.application.use_cases.pipeline.compute_transform_use_case import ComputeTransformUseCase
from edi.application.use_cases.pipeline.delivery_use_case import DeliveryUseCase
from edi.config.settings import AppSettings

logger = structlog.get_logger(__name__)

# --- Test Data Generation ---


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


EDI_PAYLOAD = b"ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *210101*1200*U*00401*000000001*0*T*:~GS*PO*SENDER*RECEIVER*20210101*1200*1*X*004010~ST*850*0001~BEG*00*NE*456**20210101~SE*3*0001~GE*1*1~IEA*1*000000001~"


@pytest.mark.skip(reason="Needs real DB fixtures for E2E")
@pytest.mark.integration
@pytest.mark.asyncio
async def test_inbound_flow_e2e(
    session: AsyncSession,
    global_session: AsyncSession,
    client: httpx.AsyncClient,
    override_get_secret_store,
) -> None:
    """
    E2E Test:
    1. Start dummy Webhook Receiver.
    2. Configure Webhook & InboundRoute in DB.
    3. Send AS2 Payload.
    4. Wait for Delivery and assert Webhook Receiver got JSON.
    """

    received_webhook_payloads = []

    async def webhook_handler(request: web.Request) -> web.Response:
        data = await request.json()
        received_webhook_payloads.append(data)
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_post("/webhook", webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 9999)
    await site.start()

    try:
        tenant_id = 0

        # Create Webhook (Global DB)
        webhook = GlobalWebhook(
            id=generate_id("id"),
            tenant_id=tenant_id,
            name="E2E Webhook",
            url="http://127.0.0.1:9999/webhook",
            active=True,
        )
        global_session.add(webhook)

        # Create InboundRoute (Global DB)
        inbound_route = ControlPlaneInboundRoute(
            tenant_id=tenant_id,
            isa_sender_id="SENDER",
            isa_receiver_id="RECEIVER",
            transaction_type=None,
            webhook_id=webhook.id,
            active=True,
        )
        global_session.add(inbound_route)

        # Create Local and Remote AS2 Partners for validation
        local_priv, local_cert = generate_self_signed_cert()
        _remote_priv, remote_cert = generate_self_signed_cert()

        # Base64 encode certificates for database
        local_cert_b64 = base64.b64encode(local_cert).decode("utf-8")
        remote_cert_b64 = base64.b64encode(remote_cert).decode("utf-8")

        # Seed the fake vault
        local_priv_ref = await override_get_secret_store.store_private_key(local_priv)

        # Using Tenant DB for data plane partnerships
        local_partner = AS2Partner(
            tenant_id=tenant_id,
            as2_id="RECEIVER",
            is_local=True,
            certificate_data=local_cert_b64,
            private_key_vault_ref=local_priv_ref,
        )
        remote_partner = AS2Partner(
            tenant_id=tenant_id,
            as2_id="SENDER",
            is_local=False,
            certificate_data=remote_cert_b64,
        )
        global_session.add_all([local_partner, remote_partner])
        await global_session.flush()

        partnership = AS2Partnership(
            tenant_id=tenant_id,
            local_partner_id=local_partner.id,
            remote_partner_id=remote_partner.id,
            active=True,
            encryption_algorithm="AES_256_CBC",
            signing_algorithm="SHA256",
        )
        global_session.add(partnership)
        await session.commit()
        await global_session.commit()

        # Replicate to Data Plane since this runs outside standard provisioning sync

        t_webhook = DataPlaneWebhook(
            id=webhook.id,
            tenant_id=tenant_id,
            name="E2E Webhook",
            url="http://127.0.0.1:9999/webhook",
            active=True,
        )
        t_route = DataPlaneInboundRoute(
            tenant_id=tenant_id,
            isa_sender_id="SENDER",
            isa_receiver_id="RECEIVER",
            transaction_type=None,
            webhook_id=webhook.id,
            active=True,
        )
        session.add(t_webhook)
        session.add(t_route)
        await session.commit()

        # Build unencrypted/unsigned AS2 payload for simplicity in E2E
        msg = build_outbound_message(
            payload=EDI_PAYLOAD,
            as2_from="SENDER",
            as2_to="RECEIVER",
        )

        # Send to API AS2 server
        response = await client.post(
            "/as2/receive",
            content=msg.body,
            headers=msg.headers,
        )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Text: {response.text}"
        )
        assert "application/edi-consent" in response.headers.get("content-type", "")

        # To avoid running full worker pipeline in a unit test, we will instantiate the services directly

        # 1. Manually run ComputeTransformUseCase
        settings = AppSettings()

        uow = SqlAlchemyDataPlaneUnitOfWork(session, settings, S3StorageClient("test", None))
        translate_svc = ComputeTransformUseCase(uow, BotsTransformerAdapter())

        # Get trace_id from DB
        res = await session.execute(select(EdiMessage).where(EdiMessage.sender_id == "SENDER"))
        edi_msg = res.scalar_one()
        trace_id = str(edi_msg.trace_id)

        try:
            await translate_svc.execute(trace_id, standard="X12", transaction_type="850")
        except Exception as e:  # noqa: BLE001
            # If bots is not running, we use a pure FakeTransformerAdapter instead of a mock
            if "Connection" in str(e):
                from edi.testing.fakes.pipeline_fakes import FakeTransformerAdapter

                translate_svc.transformer = FakeTransformerAdapter()
                await translate_svc.execute(trace_id, standard="X12", transaction_type="850")

        # 2. Manually run Deliver

        @contextlib.asynccontextmanager
        async def mock_uow_factory():
            yield uow

        deliver_svc = DeliveryUseCase(
            uow_factory=mock_uow_factory,
            router_factory=lambda _uow: MagicMock(),
        )
        await deliver_svc.execute(trace_id)

        assert len(received_webhook_payloads) == 1
        assert received_webhook_payloads[0]["fake"] == "json"

    finally:
        await runner.cleanup()
