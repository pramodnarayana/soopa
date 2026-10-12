# Flowwolf EDI Trading Partner Testing Setup

This document outlines the configurations and certificates needed by the QA/Testing team to create **Local Trading Partners** (Flowwolf EDI itself) and **Remote Trading Partners** (OpenAS2 Test Server) in the Flowwolf EDI UI.

These configurations are safe for integration testing and do not contain production secrets.

---

## 1. Certificates
The required certificates have been pre-generated for you in this repository under the `docs/testing/certs/` folder.

You will need to upload these into the Flowwolf EDI Key Management / Certificate UI:

1. **Flowwolf Private Key (For the Local TP)**
   * **File**: `docs/testing/certs/flowwolf_certs.p12`
   * **Password**: `flowwolf`
   * **Alias**: `flowwolf_as2_alias`

2. **OpenAS2 Public Key (For the Remote TP)**
   * **File**: `docs/testing/certs/openas2_public.cer`
   * *(No password required as it is a public key)*
   * **Alias**: `openas2b_alias`

*(Note: The OpenAS2 server's keystore is already pre-configured to trust the `flowwolf_public.cer` key.)*

---

## 2. Local Environment (Docker)

### A. Create the Local Trading Partner (FlowwolfEDI)
This represents our internal EDI system running locally.
* **Name**: `Flowwolf Local`
* **AS2 ID**: `FLOWWOLF_LOCAL_AS2`
* **Email**: `as2@local.flowwolfedi.local`
* **Private Certificate**: Select the `flowwolf_certs.p12` you uploaded.

### B. Create the Remote Trading Partner (OpenAS2 Test Server)
This represents the external partner that we will send to and receive from.
* **Name**: `OpenAS2`
* **AS2 ID**: `OPEN_AS2`
* **Email**: `as2@openas2.local`
* **AS2 URL**: `http://openas2:10080/`
* **Public Certificate**: Select the `openas2_public.cer` you uploaded.

---

## 3. AWS Staging Environment

### A. Create the Local Trading Partner (FlowwolfEDI Staging)
This represents our internal EDI system running on the AWS Staging Cluster.
* **Name**: `Flowwolf Staging`
* **AS2 ID**: `FLOWWOLF_STAGING_AS2`
* **Email**: `as2@staging.flowwolfedi.local`
* **Private Certificate**: Select the `flowwolf_certs.p12` you uploaded.

### B. Create the Remote Trading Partner (OpenAS2 Test Server)
This represents the external OpenAS2 partner deployed to AWS.
* **Name**: `OpenAS2`
* **AS2 ID**: `OPEN_AS2`
* **Email**: `as2@openas2.local`
* **AS2 URL**: `https://openas2.staging.flowwolf.io/as2/inbox`
* **Public Certificate**: Select the `openas2_public.cer` you uploaded.

---

## 4. Partnership Configuration (Inbound & Outbound)
When establishing the Partnership / Communication channel in the Flowwolf EDI UI, use these exact parameters for both directions:

* **Protocol**: `AS2`
* **Content Transfer Encoding**: `binary`
* **Encryption Algorithm**: `3DES`
* **Signature Algorithm**: `SHA-256`
* **MDN (Receipts)**: Required (Synchronous or Asynchronous)
* **MDN Signature Algorithm**: `SHA-256`

---

## 5. Raw PEM Certificates

For systems that prefer direct raw certificate pasting instead of uploading `.p12`/`.cer` files, use the blocks below.

### Flowwolf EDI - Private Key & Public Certificate
*(Use this to configure the Local TP - Flowwolf)*

```pem
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCOLPeTcofLn//F
Nst7APDxaYSb8Ifn9DFh4cWH/Qd30Rg+CH2WXW4Xaz4jDs4G0isk5RTI1iS2ytz3
gwX65GuW9Y/18VLVOSk/2P2GFm8kaeApavGI6L5qZQFlUcFPlK0RFws56AsRE1Uv
fJgR8M4UFZeXptTncRZFsaftQ4v3U5/UyCj8KhxdNySMPOlw/mCb8eAzx5EMgodC
L1Lqqxf7VzIq6uNeXXX99xkkfLNhRbLVdBj4O6ALtaQL+1rk7eUOimAjGrs5VNHJ
Qt7/FsDWQDBmTEOU3fUDr8gNxXIUGvI1lOrqjE5rBy9QVCE/yBGlnN5+T6tQDhl5
IN+5Tw0bAgMBAAECggEAFM+eObYFDJhR/xMjO9EKc7vnTlAqBJjo9ZPvrxUpl69C
pinmADGS4Niw0r7jB3qSGCd0IGXAIAWXzJ8gK/ZtjT5KoUx+vHlOgWsIySzVffYF
euqNimXPIZHBX4xVCIoRvzOpUAOYQxqaWIYbWFzwPV5fvzILbglOokr78q31efFJ
57/e7CAdAUMnva0A5f+2FfJW+rle9MMPvtjlXfImPUnJ4j7Y5E74BC3bxea6Bnly
oFNyeql3QeevtnbFNKp6d18wxp8AwI5EwF3hSind1QRd6sX3t7tW05hvF4RZkME6
LSxIgEKk1+jFd9bIaXxZHuVbDRZ+LtSKh2+xGqHymQKBgQDk1v07Syy7njwFb2lx
6Uu/iv6SPeevtdKVBL9M+PeE9KncbP8Yvyhlx1ZiErLvuTKGWdrUIhX1APr4U+jT
7omEHbEQUezAeolRKkS4O35fHmC6VbF3iixdMRZFoZosXVd6Bo8w3qbae1jnt+to
P9iQnsfaM8krgqHAGrAuv3ShdQKBgQCfDMvYNYnuJVFlzwQgiII+tdUmtBV5eQFT
TMPWr+7drqOJWhhvB+1nBPffjwobQwB9pC+0KwmENCXFu+b7+DBB1CuicT+3Pb2C
vS9DV/4b/ZJd4iyEUUbp6TIiwQu6JId0Rt4Ucc6G14pFH7pLogG9uyoKSJ28UWS7
5QoD7zsSTwKBgQCh2ayhEzpAOFobPgFGH8sDXjtPE5maHO8jlof22N+3mZPJ4w1J
Y2ofEi12j+Meyc2CWGr9Pl5pOphGqpIx0rRQTO++qzLXr9MPJOYVp35pqAKhx5oN
Ahz+jIlEFlgEqMAF/j2oQtGgFT18JgjJYt646pRPL/FIZMwiIr4ZUjAbQQKBgHr0
gYGbog2ge9SgvSgJX+bq2uUYwqEtkoC7D4qgZ6CoqXQ9WjY7gqPpi1YgVkfM/Ewk
6Vv3CVxSlADQyjhwHZ5GT5U8x2z5JdA0QJ1nIOKynLxHZPLFgnTB+igz5MT6CF0z
i+tyL56+cf4OEQ73JzFtx4o7qPU0VxOKdLul7ZyxAoGADZ+GPjFNeFMkjMhbvTdi
tFN707PUIxrjXaj9wl3HG1lXdwiur4kpqQyaoptQ9YC8mjymmNVNvmZyTez1DBCg
WwOiP//JXceRmGhJCOYl6mR1JRg6wLg1RORngXbvurdwOpySipTPEaW4ysp3i54B
q0UItoTOFghvmKGDgyPsbyg=
-----END PRIVATE KEY-----
-----BEGIN CERTIFICATE-----
MIICzTCCAbWgAwIBAgIEHH8mRzANBgkqhkiG9w0BAQsFADAXMRUwEwYDVQQDEwxG
bG93d29sZiBBUzIwHhcNMjYxMDA4MTcyMDEyWhcNMzYxMDA1MTcyMDEyWjAXMRUw
EwYDVQQDEwxGbG93d29sZiBBUzIwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEK
AoIBAQCOLPeTcofLn//FNst7APDxaYSb8Ifn9DFh4cWH/Qd30Rg+CH2WXW4Xaz4j
Ds4G0isk5RTI1iS2ytz3gwX65GuW9Y/18VLVOSk/2P2GFm8kaeApavGI6L5qZQFl
UcFPlK0RFws56AsRE1UvfJgR8M4UFZeXptTncRZFsaftQ4v3U5/UyCj8KhxdNySM
POlw/mCb8eAzx5EMgodCL1Lqqxf7VzIq6uNeXXX99xkkfLNhRbLVdBj4O6ALtaQL
+1rk7eUOimAjGrs5VNHJQt7/FsDWQDBmTEOU3fUDr8gNxXIUGvI1lOrqjE5rBy9Q
VCE/yBGlnN5+T6tQDhl5IN+5Tw0bAgMBAAGjITAfMB0GA1UdDgQWBBQAKZp9TQIL
147C4l+gBfvnzCpm8DANBgkqhkiG9w0BAQsFAAOCAQEAJudgzzteWnwVZCgB9NVK
Hd3jF31MR7uh3a20S9b17kB/Sdj2YT/DUMwjo/Bq3MOPjYzad9+j1aCr0jjiPaKL
u1IqOy0AmMSe3qGoiAW4isOy20j2g6LNYZlAR6KBBHpkE6zhRk9E/7o+fCuTHhFl
qvshXdsmW3Fuvkb3/gOHlLOZUbeGOZjaPlpshguLnPgN3RUXObmkXh3M0t2x9Zaf
q+M6V3Ry+h+B7iizLY1YU6wQ7Fau25Be/EiOT5jpCkZAfVI0xZjMkat71UF8OT0r
ac7lAosxKuwYEGTgBqjqvfDIE4YrsjcgAA3VS4aMXwpdoIxs2dKYdj8Br7ZfuX1j
oA==
-----END CERTIFICATE-----
```

### OpenAS2 - Public Certificate
*(Use this to configure the Remote TP - OpenAS2)*

```pem
-----BEGIN CERTIFICATE-----
MIICuTCCAaECBFQIMB4wDQYJKoZIhvcNAQEFBQAwIDELMAkGA1UEBhMCQVQxETAP
BgNVBAMMCE9wZW5BUzJCMCAXDTE0MDkwNDA5MjU1MFoYDzIxMTQwODExMDkyNTUw
WjAgMQswCQYDVQQGEwJBVDERMA8GA1UEAwwIT3BlbkFTMkIwggEiMA0GCSqGSIb3
DQEBAQUAA4IBDwAwggEKAoIBAQCRPos6J39UlTnWsvyqiBAqdFavnhwdTC0PVc8p
UF0qXwUUM9eNuU8wyBwBveDassLAYNyd9QySd9lXuxeKbNpEUCJU4z7d+NEDEfTi
YgHbHR3Tx9YvW657N+eH+++bpdYBeIpFqaGJo8EebZ4p7R/DRa/791Dv6YUEeF9x
sScJjVedB+lW20Hq63lt8gWBUP7pzZBYI2puFLrLR52hltkRWVyBnffteIr1CWU4
2oHAtW/4VSP4W2s/CJHf7uYn7EZeO42qEDefdHqQIdklssdJ3wlLiy2hwaTcP9R2
7oOTuqNsrcXimxNMkmusA42m4I8+Y+WyzBO/XmAzc1QBO6ibAgMBAAEwDQYJKoZI
hvcNAQEFBQADggEBAHcDfWCDuwGipHGkutyImrZfpK92pVewCETxc02QlFNEt+10
jSxLziUb1HylqehnAmI0R6E1b13bb5UCUdqVnlWJopiNaKRu3iUZqDTPzPI3nmsd
CmkEHbM3Kse4DchVxHU6VqcYoSUiO3CeYPVY7F+FbBDZ/QvweFCaMz/mNtvehwDm
PmeK8ne6e93yoo+73FLEwHLtc4UCP9mXEE0EI0e8t2YMjOnzt25Mro3/DYK7nKPY
/ZQoz02pN7VBvo8PlGPLLg7Qo12Ee4Vl9Yb9phPeNb3DXQ+oKXB/6b23BPRvA3y7
VKk4q57ieqQlq+6dA03JB8ORkPBODUTO/zAtA+4=
-----END CERTIFICATE-----
```
