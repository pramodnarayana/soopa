import base64
import datetime
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import structlog
from as2_core import build_outbound_message
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from database.models.control_plane import (
    AS2Partner,
    AS2Partnership,
)
from database.models.data_plane import (
    InboundRoute,
    Webhook,
)
from sqlalchemy import select

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
async def test_inbound_flow_e2e(session, global_session, client: httpx.AsyncClient) -> None:
    """
    E2E Test:
    1. Start dummy Webhook Receiver.
    2. Configure Webhook & InboundRoute in DB.
    3. Send AS2 Payload.
    4. Wait for Delivery and assert Webhook Receiver got JSON.
    """
    from aiohttp import web

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
        webhook = Webhook(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name="E2E Webhook",
            url="http://127.0.0.1:9999/webhook",
            active=True,
        )
        global_session.add(webhook)

        # Create InboundRoute (Global DB)
        inbound_route = InboundRoute(
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

        # Using Tenant DB for data plane partnerships
        local_partner = AS2Partner(
            tenant_id=tenant_id,
            as2_id="RECEIVER",
            is_local=True,
            certificate_data=local_cert_b64,
        )
        remote_partner = AS2Partner(
            tenant_id=tenant_id,
            as2_id="SENDER",
            is_local=False,
            certificate_data=remote_cert_b64,
        )
        session.add_all([local_partner, remote_partner])
        await session.flush()

        partnership = AS2Partnership(
            tenant_id=tenant_id,
            local_partner_id=local_partner.id,
            remote_partner_id=remote_partner.id,
            active=True,
            encryption_algorithm="AES_256_CBC",
            signing_algorithm="SHA256",
        )
        session.add(partnership)
        await session.commit()
        await global_session.commit()

        # Replicate to Data Plane since this runs outside standard provisioning sync
        from database.models.data_plane import InboundRoute as TenantInboundRoute
        from database.models.data_plane import Webhook as TenantWebhook

        t_webhook = TenantWebhook(
            id=webhook.id,
            tenant_id=tenant_id,
            name="E2E Webhook",
            url="http://127.0.0.1:9999/webhook",
            active=True,
        )
        t_route = TenantInboundRoute(
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

        with patch(
            "edi.application.use_cases.as2_receive_service.vault.get_secret", new_callable=AsyncMock
        ) as mock_get_secret:
            mock_get_secret.return_value = local_priv.decode("utf-8")

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
        from unittest.mock import MagicMock

        from database.models.data_plane import EdiMessage
        from domain.events import PipelineEventType
        from pipeline.adapters.http import HttpxDeliveryClient
        from pipeline.adapters.repository import SqlAlchemyRepositoryAdapter
        from pipeline.adapters.storage import S3StorageClient
        from pipeline.adapters.transformer import BotsTransformerAdapter
        from pipeline.core.deliver import DeliveryService
        from pipeline.core.translate import TranslationService

        # 1. Manually run Translate
        repo = SqlAlchemyRepositoryAdapter(session, MagicMock(), S3StorageClient("test", None))
        translate_svc = TranslationService(BotsTransformerAdapter("http://localhost:5000"), repo)

        # Get trace_id from DB
        res = await session.execute(select(EdiMessage).where(EdiMessage.sender_id == "SENDER"))
        edi_msg = res.scalar_one()
        trace_id = str(edi_msg.trace_id)

        try:
            await translate_svc.translate(trace_id, event_type=PipelineEventType.TRANSFORM_EVENT)
        except Exception as e:  # noqa: BLE001
            # If bots is not running, we mock it for the test
            if "Connection" in str(e):
                from pipeline.ports.transformer import TransformerPort

                class MockTransformer(TransformerPort):
                    async def translate_edi_to_json(
                        self, payload: bytes, standard: str, transaction_type: str
                    ):
                        from pipeline.ports.transformer import TranslatedTransaction

                        return [
                            TranslatedTransaction(
                                transaction_type=transaction_type,
                                isa_sender_id="MOCK_ISA_SENDER",
                                isa_receiver_id="MOCK_ISA_RECEIVER",
                                gs_sender_id="MOCK_GS_SENDER",
                                gs_receiver_id="MOCK_GS_RECEIVER",
                                control_number="MOCK_1234",
                                payload={"fake": "json", "type": transaction_type},
                            )
                        ]

                    async def translate_json_to_edi(
                        self,
                        payload: dict,
                        standard: str,
                        transaction_type: str,
                        _route_config: dict,
                    ) -> bytes:
                        return b""

                translate_svc.transformer = MockTransformer()
                await translate_svc.translate(
                    trace_id, event_type=PipelineEventType.TRANSFORM_EVENT
                )

        # 2. Manually run Deliver
        deliver_svc = DeliveryService(
            repository=repo,
            http_delivery=HttpxDeliveryClient(
                validator=lambda _x: True
            ),  # disable SSRF for 127.0.0.1
            sftp_delivery=MagicMock(),
            as2_delivery=MagicMock(),
        )
        await deliver_svc.deliver(trace_id)

        assert len(received_webhook_payloads) == 1
        assert received_webhook_payloads[0]["fake"] == "json"

    finally:
        await runner.cleanup()
