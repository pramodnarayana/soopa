import email

smime = b"""MIME-Version: 1.0
Content-Disposition: attachment; filename="smime.p7m"
Content-Type: application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"
Content-Transfer-Encoding: base64

MIIBkwYJKoZIhvc=
"""
msg = email.message_from_bytes(smime)
print("CT:", msg.get("Content-Type"))
print("CTE:", msg.get("Content-Transfer-Encoding"))
