import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = issuer = x509.Name([])
cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.now(datetime.UTC))
    .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=10))
    .sign(key, hashes.SHA256())
)

builder = pkcs7.PKCS7SignatureBuilder().set_data(b"test payload")
builder = builder.add_signer(cert, key, hash_algorithm=hashes.SHA256())
signed = builder.sign(serialization.Encoding.SMIME, options=[])
print(repr(signed[:150]))
