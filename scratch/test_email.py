import email
from email import policy

boundary = b"----Boundary_Test_12345"
entity = (
    b'Content-Type: multipart/signed; protocol="application/pkcs7-signature"; micalg="sha-256"; boundary="'
    + boundary[4:]
    + b'"\r\n'
    b"\r\n"
)
msg = email.message_from_bytes(entity, policy=policy.HTTP)
print(msg.get_boundary())
print(msg.items())
