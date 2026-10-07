import uuid

from seedwork import generate_id

from as2_server.main import app

"""
Shared test fixtures for the AS2 Server integration tests.

Key fixtures:
  - sender_keypair / receiver_keypair: Real RSA-2048 keys + self-signed X.509 certs
  - signed_as2_payload: A real multipart/signed AS2 body
  - encrypted_as2_payload: A real enveloped PKCS#7 AS2 body
  - as2_client: FastAPI AsyncClient wired with NoOp observability + faked DB
"""

import asyncio
import contextlib
import datetime
import os
import subprocess
import tempfile
from collections.abc import AsyncGenerator
from typing import NamedTuple

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from database.provider import get_async_engine
from database.testing import get_test_shard_url_async
from dotenv import load_dotenv
from edi.adapters.outbound.database.models.control_plane import (
    AS2Partner,
    AS2Partnership,
    InboundRoute,
)
from edi.adapters.outbound.security.smime_crypto_service import SmimeCryptoService
from httpx import ASGITransport, AsyncClient
from identity.domain.identity_context import PLATFORM_TENANT_ID
from observability import NoOpLogger, NoOpMetrics, NoOpTracer, ObservabilityProvider
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from as2_server.dependencies import get_global_session, get_session, get_vault_service

load_dotenv()

"""
Shared test fixtures for the AS2 Server integration tests.

Key fixtures:
  - sender_keypair / receiver_keypair: Real RSA-2048 keys + self-signed X.509 certs
  - signed_as2_payload: A real multipart/signed AS2 body
  - encrypted_as2_payload: A real enveloped PKCS#7 AS2 body
  - as2_client: FastAPI AsyncClient wired with NoOp observability + faked DB
"""


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def global_db_engine():
    db_url = os.environ["DATABASE_URL"]
    engine = get_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def tenant_db_engine():
    global_url = os.environ["DATABASE_URL"]
    db_url = await get_test_shard_url_async(global_url)
    engine = get_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def global_db_connection(global_db_engine):
    connection = await global_db_engine.connect()
    transaction = await connection.begin()
    yield connection
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def tenant_db_connection(tenant_db_engine):
    connection = await tenant_db_engine.connect()
    transaction = await connection.begin()
    yield connection
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def global_db_session(global_db_connection):
    SessionLocal = async_sessionmaker(
        bind=global_db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        info={"session_type": "global"},
        join_transaction_mode="create_savepoint",
    )
    session = SessionLocal()
    yield session
    await session.close()


@pytest_asyncio.fixture(scope="function")
async def tenant_db_session(tenant_db_connection):
    SessionLocal = async_sessionmaker(
        bind=tenant_db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        info={"session_type": "tenant"},
        join_transaction_mode="create_savepoint",
    )
    session = SessionLocal()
    yield session
    await session.close()


class FakeDatabaseRouter:
    def __init__(self, global_session, tenant_session):
        self.global_session = global_session
        self.tenant_session = tenant_session

    @contextlib.asynccontextmanager
    async def get_global_session(self):
        yield self.global_session

    async def get_tenant_session(self, tenant_id: str, shard_key: str, shard_url: str):
        yield self.tenant_session

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


class FakeTenantResolver:
    def __init__(self, shard_dsn: str) -> None:
        self._shard_dsn = shard_dsn

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        return ("test-shard", self._shard_dsn)

    async def resolve_routing_config(self, tenant_id: str) -> dict:
        return {}

    async def get_tenant_db_url(self, tenant_id: str) -> str:
        return self._shard_dsn


class FakeS3Storage:
    async def upload(self, tenant_id: int, message_id: str, payload: bytes) -> str:
        return f"s3://test-bucket/tenants/{tenant_id}/{message_id}.bin"

    async def download(self, storage_uri: str) -> bytes:
        return b""


class FakeHostVault:
    def __init__(self, private_key_pem: bytes):
        self.private_key_pem = private_key_pem

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        return self.private_key_pem

    async def get_secret(self, vault_ref: str) -> str:
        return self.private_key_pem.decode("utf-8")

    async def store_private_key(self, private_key_pem: bytes, category=None) -> str:
        return "fake-vault-ref"

    async def retrieve_secret(self, vault_ref: str) -> bytes:
        return self.private_key_pem

    async def delete_secret(self, vault_ref: str) -> None:
        pass


class FakePublisher:
    async def publish(self, event):
        pass


@pytest_asyncio.fixture
async def as2_client(
    sender_keypair: KeyPair,
    receiver_keypair: KeyPair,
    global_db_session,
    tenant_db_session,
    tenant_db_engine,
) -> AsyncGenerator[AsyncClient, None]:
    """
    FastAPI AsyncClient pre-configured with:
    - NoOp observability (no infra required)
    - Faked database session
    - Sender's public cert available as a known Trading Partner
    - ISA lookup results configurable via isa_lookup_config attribute
    """
    # Wire NoOp observability — tests run with zero telemetry infrastructure
    ObservabilityProvider.configure(
        tracer=NoOpTracer(),
        metrics=NoOpMetrics(),
        logger=NoOpLogger(),
    )

    # Seed the AS2 Keypair into the global_db_session
    tenant_id = PLATFORM_TENANT_ID
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
        private_key_vault_ref="fake-vault-ref",
    )
    partnership = AS2Partnership(
        id=generate_id("as2ps"),
        tenant_id=tenant_id,
        name="Test AS2 Partnership",
        local_partner_id=receiver_partner.id,
        remote_partner_id=sender_partner.id,
        active=True,
    )
    inbound_route = InboundRoute(
        id=generate_id("route"),
        tenant_id="test-tenant",
        name="Test AS2 Inbound Route",
        isa_sender_id="PARTNER",
        isa_receiver_id="SOOPAEDI",
        transaction_type="850",
        as2_partner_id=sender_partner.id,
        active=True,
    )
    global_db_session.add_all([sender_partner, receiver_partner, partnership, inbound_route])
    await global_db_session.flush()

    # Create configurable ISA lookup state
    isa_lookup_config = ISALookupConfig()

    async def override_get_global_session() -> AsyncGenerator[AsyncSession, None]:
        yield global_db_session

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield tenant_db_session

    app.state.s3_storage = FakeS3Storage()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_global_session] = override_get_global_session

    app.dependency_overrides[get_vault_service] = lambda: FakeHostVault(
        receiver_keypair.private_key_pem
    )

    # Provide the fake db router and tenant resolver
    shard_dsn = str(tenant_db_engine.url)
    app.state.db_router = FakeDatabaseRouter(
        global_session=global_db_session, tenant_session=tenant_db_session
    )
    app.state.tenant_resolver = FakeTenantResolver(shard_dsn=shard_dsn)

    app.state.publisher = FakePublisher()
    app.state.crypto_service = SmimeCryptoService()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Attach the config to the client so tests can modify it
        client.isa_lookup_config = isa_lookup_config
        yield client

        app.dependency_overrides.clear()
