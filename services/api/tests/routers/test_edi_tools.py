from api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

SAMPLE_X12 = b"""ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *210101*1200*U*00401*000000001*0*P*>~
GS*FA*SENDER*RECEIVER*20210101*1200*1*X*004010~
ST*997*0001~
AK1*PO*1~
AK9*A*1*1*1~
SE*4*0001~
GE*1*1~
IEA*1*000000001~"""


def test_transform_edi_to_json_valid():
    response = client.post(
        "/api/edi-tools/transform",
        json={"action": "EDI_TO_JSON", "payload": SAMPLE_X12.decode("utf-8")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert "interchange_ISA" in data["result"]


def test_transform_edi_to_json_invalid_edi():
    response = client.post(
        "/api/edi-tools/transform", json={"action": "EDI_TO_JSON", "payload": "GARBAGE_PAYLOAD"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert "GARBAGE" in data["error"]


def test_transform_json_to_edi_valid():
    # First get valid JSON
    res = client.post(
        "/api/edi-tools/transform",
        json={"action": "EDI_TO_JSON", "payload": SAMPLE_X12.decode("utf-8")},
    )
    import json

    ast_envelope = json.loads(res.json()["result"])
    ast_json = json.dumps(ast_envelope["data"])

    # Then translate back
    response = client.post(
        "/api/edi-tools/transform", json={"action": "JSON_TO_EDI", "payload": ast_json}
    )
    assert response.status_code == 200
    data = response.json()

    # We must assert 'valid' is True, but right now there's an error about payload schema if we send ast_json directly
    # Wait, ast_json is a string containing JSON.
    assert data["valid"] is True
    assert "ISA*00*" in data["result"]


def test_transform_json_to_edi_invalid_json_format():
    response = client.post(
        "/api/edi-tools/transform", json={"action": "JSON_TO_EDI", "payload": "{invalid json}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert data["error"] is not None


def test_transform_invalid_action():
    response = client.post(
        "/api/edi-tools/transform", json={"action": "INVALID_ACTION", "payload": "data"}
    )
    assert response.status_code in (422, 400)
