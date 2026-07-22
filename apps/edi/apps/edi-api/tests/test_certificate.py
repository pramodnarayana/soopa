from api.domain.certificate import generate_self_signed_cert


def test_generate_self_signed_cert():
    key_pem, cert_pem = generate_self_signed_cert("Test AS2")

    assert b"BEGIN CERTIFICATE" in cert_pem
    assert b"END CERTIFICATE" in cert_pem
    assert b"BEGIN PRIVATE KEY" in key_pem
    assert b"END PRIVATE KEY" in key_pem
