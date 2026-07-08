import datetime

import endesive.signer
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from security.smime import verify_signature


def test_verify_signature_native_endesive():
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    public_key = private_key.public_key()

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "soopaedi test")])

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

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    raw_payload = (
        b"Content-Type: text/plain\r\n\r\nHello World! This is a simple English sentence payload."
    )

    datas = endesive.signer.sign(raw_payload, private_key, cert, [], "sha256")

    boundary = b"----Boundary_Test_12345"

    entity = (
        b'Content-Type: multipart/signed; protocol="application/pkcs7-signature"; micalg="sha-256"; boundary="'
        + boundary[4:]
        + b'"\r\n'
        b"\r\n"
        b"--" + boundary[4:] + b"\r\n" + raw_payload + b"\r\n"
        b"--" + boundary[4:] + b"\r\n"
        b'Content-Type: application/pkcs7-signature; name="smime.p7s"\r\n'
        b"Content-Transfer-Encoding: binary\r\n"
        b'Content-Disposition: attachment; filename="smime.p7s"\r\n'
        b"\r\n" + datas + b"\r\n"
        b"--" + boundary[4:] + b"--\r\n"
    )

    is_valid, extracted_payload = verify_signature(entity, cert_pem)

    assert is_valid is True
    assert extracted_payload == raw_payload


if __name__ == "__main__":
    test_verify_signature_native_endesive()
