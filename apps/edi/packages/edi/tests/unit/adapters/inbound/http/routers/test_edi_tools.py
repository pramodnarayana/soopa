import json

import pytest
from fastapi.testclient import TestClient

from edi.module import create_edi_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("IDENTITY_AUTHORIZATION_URL", "http://localhost:8080")
    monkeypatch.setenv("IDENTITY_TOKEN_URL", "http://localhost:8080")
    monkeypatch.setenv("IDENTITY_ISSUER", "http://localhost:8080")
    monkeypatch.setenv("IDENTITY_JWKS_URL", "http://localhost:8080")
    monkeypatch.setenv("IDENTITY_USERINFO_URL", "http://localhost:8080")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8080")
    app = create_edi_app()
    return TestClient(app)


SAMPLE_X12 = b"""ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *210101*1200*U*00401*000000001*0*P*>~
GS*FA*SENDER*RECEIVER*20210101*1200*1*X*004010~
ST*997*0001~
AK1*PO*1~
AK9*A*1*1*1~
SE*4*0001~
GE*1*1~
IEA*1*000000001~"""


def test_transform_edi_to_json_valid(client: TestClient):
    response = client.post(
        "/api/v1/edi-tools/transform",
        json={"action": "EDI_TO_JSON", "payload": SAMPLE_X12.decode("utf-8")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert "interchange_ISA" in data["result"]


def test_transform_edi_to_json_invalid_edi(client: TestClient):
    response = client.post(
        "/api/v1/edi-tools/transform", json={"action": "EDI_TO_JSON", "payload": "GARBAGE_PAYLOAD"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert "GARBAGE" in data["error"]


def test_transform_json_to_edi_valid(client: TestClient):
    # First get valid JSON
    res = client.post(
        "/api/v1/edi-tools/transform",
        json={"action": "EDI_TO_JSON", "payload": SAMPLE_X12.decode("utf-8")},
    )

    ast_envelope = json.loads(res.json()["result"])
    ast_json = json.dumps(ast_envelope["data"])

    # Then transform back
    response = client.post(
        "/api/v1/edi-tools/transform", json={"action": "JSON_TO_EDI", "payload": ast_json}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["valid"] is True
    assert "ISA*00*" in data["result"]


def test_transform_json_to_edi_invalid_json_format(client: TestClient):
    response = client.post(
        "/api/v1/edi-tools/transform", json={"action": "JSON_TO_EDI", "payload": "{invalid json}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert data["error"] is not None


def test_transform_invalid_action(client: TestClient):
    response = client.post(
        "/api/v1/edi-tools/transform", json={"action": "INVALID_ACTION", "payload": "data"}
    )
    assert response.status_code in (422, 400)
