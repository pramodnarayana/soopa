"""
Shared test fixtures for the AS2 Server integration tests.

Key fixtures:
  - sender_keypair / receiver_keypair: Real RSA-2048 keys + self-signed X.509 certs
  - signed_as2_payload: A real multipart/signed AS2 body
  - encrypted_as2_payload: A real enveloped PKCS#7 AS2 body
  - as2_client: FastAPI AsyncClient wired with NoOp observability + mocked DB
"""

import datetime
import os
import subprocess
import tempfile
from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from httpx import ASGITransport, AsyncClient
from observability import NoOpLogger, NoOpMetrics, NoOpTracer, ObservabilityProvider


class KeyPair(NamedTuple):
    private_key_pem: bytes
    public_cert_pem: bytes
    as2_id: str


def _generate_keypair(as2_id: str) -> KeyPair:
    """Generates a real RSA-2048 private key and self-signed X.509 certificate."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, as2_id),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "EDI AS2 Test"),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .sign(private_key, hashes.SHA256())
    )

    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    return KeyPair(
        private_key_pem=private_key_pem,
        public_cert_pem=public_cert_pem,
        as2_id=as2_id,
    )


@pytest.fixture(scope="session")
def sender_keypair() -> KeyPair:
    """The Trading Partner (sender) key pair."""
    return _generate_keypair("PARTNER-AS2-ID")


@pytest.fixture(scope="session")
def receiver_keypair() -> KeyPair:
    """Our server (receiver) key pair."""
    return _generate_keypair("SOOPAEDI-AS2-ID")


@pytest.fixture(scope="session")
def edi_payload() -> bytes:
    """A minimal but realistic EDI X12 850 Purchase Order payload."""
    return (
        b"ISA*00*          *00*          *ZZ*PARTNER         *ZZ*SOOPAEDI       "
        b"*260101*1200*^*00501*000000001*0*P*:\n"
        b"GS*PO*PARTNER*SOOPAEDI*20260101*1200*1*X*005010\n"
        b"ST*850*0001\n"
        b"BEG*00*NE*PO-12345**20260101\n"
        b"PO1*1*10*EA*9.99**VP*ITEM-001\n"
        b"CTT*1\n"
        b"SE*5*0001\n"
        b"GE*1*1\n"
        b"IEA*1*000000001\n"
    )


@pytest.fixture(scope="session")
def signed_as2_payload(sender_keypair: KeyPair, edi_payload: bytes) -> bytes:
    """Creates a real S/MIME multipart/signed AS2 payload using the sender's private key."""
    with (
        tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as key_f,
        tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as cert_f,
        tempfile.NamedTemporaryFile(delete=False) as in_f,
    ):
        key_f.write(sender_keypair.private_key_pem)
        cert_f.write(sender_keypair.public_cert_pem)
        in_f.write(edi_payload)
        key_f.flush()
        cert_f.flush()
        in_f.flush()

    try:
        result = subprocess.run(
            [
                "openssl",
                "smime",
                "-sign",
                "-in",
                in_f.name,
                "-signer",
                cert_f.name,
                "-inkey",
                key_f.name,
                "-outform",
                "SMIME",
                "-nodetach",
            ],
            capture_output=True,
            check=True,
        )
        return result.stdout
    finally:
        os.unlink(key_f.name)
        os.unlink(cert_f.name)
        os.unlink(in_f.name)


@pytest.fixture(scope="session")
def encrypted_as2_payload(receiver_keypair: KeyPair, edi_payload: bytes) -> bytes:
    """Creates a real S/MIME PKCS#7 enveloped payload encrypted to the receiver's public cert."""
    with (
        tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as cert_f,
        tempfile.NamedTemporaryFile(delete=False) as in_f,
    ):
        cert_f.write(receiver_keypair.public_cert_pem)
        in_f.write(edi_payload)
        cert_f.flush()
        in_f.flush()

    try:
        result = subprocess.run(
            [
                "openssl",
                "smime",
                "-encrypt",
                "-aes256",
                "-in",
                in_f.name,
                "-outform",
                "SMIME",
                cert_f.name,
            ],
            capture_output=True,
            check=True,
        )
        return result.stdout
    finally:
        os.unlink(cert_f.name)
        os.unlink(in_f.name)


@pytest_asyncio.fixture
async def as2_client(sender_keypair: KeyPair, receiver_keypair: KeyPair) -> None:
    """
    FastAPI AsyncClient pre-configured with:
    - NoOp observability (no infra required)
    - Mocked database session
    - Sender's public cert available as a known Trading Partner
    """
    # Wire NoOp observability — tests run with zero telemetry infrastructure
    ObservabilityProvider.configure(
        tracer=NoOpTracer(),
        metrics=NoOpMetrics(),
        logger=NoOpLogger(),
    )

    # Mock the S3 storage so tests don't try to connect to LocalStack
    class MockS3Storage:
        async def upload(self, tenant_id: int, message_id: str, payload: bytes) -> str:
            return f"s3://test-bucket/tenants/{tenant_id}/{message_id}.bin"

        async def download(self, storage_uri: str) -> bytes:
            return b""

    # Mock the DB session and repository lookups
    mock_partner = MagicMock()
    mock_partner.public_cert_pem = sender_keypair.public_cert_pem.decode()
    mock_partner.as2_id = sender_keypair.as2_id

    with (
        patch("as2_server.main.TradingPartnerRepository") as mock_partner_repo_cls,
        patch("as2_server.main.HostIdentityRepository") as mock_identity_repo_cls,
        patch("as2_server.main.AS2PayloadRepository") as mock_payload_repo_cls,
    ):
        mock_partner_repo = AsyncMock()

        def mock_find(as2_id: str) -> None:
            if as2_id == sender_keypair.as2_id:
                return mock_partner
            return None

        mock_partner_repo.find_by_as2_id.side_effect = mock_find
        mock_partner_repo_cls.return_value = mock_partner_repo

        mock_identity_repo = AsyncMock()
        # Seed the host private key so the server can decrypt incoming test messages
        mock_identity_repo.get_host_private_key.return_value = receiver_keypair.private_key_pem
        mock_identity_repo_cls.return_value = mock_identity_repo

        mock_payload_repo = AsyncMock()
        mock_payload_repo_cls.return_value = mock_payload_repo

        # Override the FastAPI S3 dependency and Session dependency
        from as2_server.main import app, get_s3_storage, get_session

        async def override_get_session() -> None:
            yield AsyncMock()

        app.dependency_overrides[get_s3_storage] = lambda: MockS3Storage()
        app.dependency_overrides[get_session] = override_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

        app.dependency_overrides.clear()
