import uuid

from seedwork import generate_id

from as2_server.main import app

"""
Shared test fixtures for the AS2 Server integration tests.

Key fixtures:
  - sender_keypair / receiver_keypair: Real RSA-2048 keys + self-signed X.509 certs
  - signed_as2_payload: A real multipart/signed AS2 body
  - encrypted_as2_payload: A real enveloped PKCS#7 AS2 body
  - as2_client: FastAPI AsyncClient wired with NoOp observability + mocked DB
"""

import asyncio
import datetime
import os
import subprocess
import tempfile

from dotenv import load_dotenv

load_dotenv()
from collections.abc import AsyncGenerator
from typing import NamedTuple

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from database.provider import get_async_engine
from httpx import ASGITransport, AsyncClient
from observability import NoOpLogger, NoOpMetrics, NoOpTracer, ObservabilityProvider
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from as2_server.dependencies import get_global_session, get_session


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    db_url = os.environ["DATABASE_URL"]
    engine = get_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_connection(db_engine):
    connection = await db_engine.connect()
    transaction = await connection.begin()
    yield connection
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_connection):
    SessionLocal = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    session = SessionLocal()
    yield session
    await session.close()


class FakeDatabaseRouter:
    def __init__(self, session):
        self.session = session

    import contextlib

    @contextlib.asynccontextmanager
    async def get_session(self, tenant_id: str):
        yield self.session

    async def close_all(self):
        pass


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
        .not_valid_before(datetime.datetime.now(datetime.UTC))
        .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365))
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


class ISALookupConfig:
    """
    Mutable container for controlling ISA lookup results per test.
    Tests can set these to control what scalar_one_or_none/fetchall return.
    """

    def __init__(self) -> None:

        # Default: single match found (existing behavior)
        self.scalar_result = generate_id("id")
        self.fetchall_result = [(uuid.uuid4(),)]
        self.first_result = None

    def set_no_match(self) -> None:
        """Configure ISA lookup to return no match."""
        self.scalar_result = None
        self.fetchall_result = []
        self.first_result = None

    def set_single_match(self, tenant_id: str = None) -> None:
        """Configure ISA lookup to return a single match."""

        tid = tenant_id if tenant_id else generate_id("id")
        self.scalar_result = tid
        self.fetchall_result = [(uuid.UUID(tid) if tenant_id else uuid.uuid4(),)]
        self.first_result = None

    def set_multiple_matches(self) -> None:
        """Configure ISA lookup to return multiple matches (ambiguous)."""

        self.scalar_result = None  # scalar_one_or_none won't be used for ambiguity check
        self.fetchall_result = [(uuid.uuid4(),), (uuid.uuid4(),)]
        self.first_result = None


@pytest_asyncio.fixture
async def as2_client(
    sender_keypair: KeyPair, receiver_keypair: KeyPair, db_session
) -> AsyncGenerator[AsyncClient, None]:
    """
    FastAPI AsyncClient pre-configured with:
    - NoOp observability (no infra required)
    - Mocked database session
    - Sender's public cert available as a known Trading Partner
    - ISA lookup results configurable via isa_lookup_config attribute
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

    # Seed the AS2 Keypair into the db_session
    from edi.adapters.outbound.database.models.control_plane import AS2Partner
    from seedwork import generate_id

    tenant_id = "test-tenant"
    sender_partner = AS2Partner(
        id=generate_id("as2p"),
        tenant_id=tenant_id,
        name="Test Sender Partner",
        as2_id=sender_keypair.as2_id,
        public_cert_pem=sender_keypair.public_cert_pem.decode(),
        is_local=False,
        active=True,
    )
    receiver_partner = AS2Partner(
        id=generate_id("as2p"),
        tenant_id=tenant_id,
        name="Test Receiver Partner",
        as2_id=receiver_keypair.as2_id,
        public_cert_pem=receiver_keypair.public_cert_pem.decode(),
        is_local=True,
        active=True,
    )
    db_session.add_all([sender_partner, receiver_partner])
    await db_session.flush()

    # Create configurable ISA lookup state
    isa_lookup_config = ISALookupConfig()

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.state.s3_storage = MockS3Storage()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_global_session] = override_get_session

    class FakeHostVault:
        def get_host_private_key(self) -> bytes:
            return receiver_keypair.private_key_pem

        def get_host_certificate(self) -> bytes:
            return receiver_keypair.public_cert_pem

    from as2_server.dependencies import get_vault_service

    app.dependency_overrides[get_vault_service] = lambda: FakeHostVault()

    # Provide the fake db router
    app.state.db_router = FakeDatabaseRouter(db_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Attach the config to the client so tests can modify it
        client.isa_lookup_config = isa_lookup_config
        yield client

        app.dependency_overrides.clear()
