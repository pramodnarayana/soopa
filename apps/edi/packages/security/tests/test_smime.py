import datetime

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from security.smime import decrypt_payload, encrypt_payload, sign_payload


def test_encrypt_decrypt_smime():
    # 1. Generate keys
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    public_key = private_key.public_key()
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC))
        .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=10))
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    payload = b"test EDI payload data"

    # 2. Encrypt
    encrypted_data = encrypt_payload(payload, cert_pem, "AES256")

    # 3. Decrypt
    decrypted = decrypt_payload(encrypted_data, private_pem, cert_pem)

    assert payload in decrypted


def test_sign_verify_smime():
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    public_key = private_key.public_key()
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC))
        .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=10))
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    payload = b"test EDI payload data to be signed"

    signed_data = sign_payload(payload, private_pem, cert_pem)

    assert b"test EDI payload data to be signed" in signed_data

    from security.smime import verify_signature

    is_valid, verified_payload = verify_signature(signed_data, cert_pem)
    assert is_valid is True
    assert verified_payload == payload
