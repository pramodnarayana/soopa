import json


def test_edi_json_round_trip():
    # 1. Create a minimal dummy EDI string to test the round trip.
    # We will use a mock Node tree since we don't have a real EDI grammar/file handy.
    from bots_core.domain.node import Node

    # Manually create an AST dictionary that represents a parsed EDI file
    original_ast = {
        "record": {
            "BOTSID": "UNB",
            "S001.0001": "UNOA",
            "S001.0002": "1",
            "S002.0004": "SENDER",
            "S003.0010": "RECEIVER",
            "S004.0017": "210101",
            "S004.0019": "1200",
            "0020": "1",
            "BOTSIDnr": "1",
        },
        "children": [
            {
                "record": {
                    "BOTSID": "UNH",
                    "0062": "1",
                    "S009.0065": "ORDERS",
                    "S009.0052": "D",
                    "S009.0054": "96A",
                    "S009.0051": "UN",
                    "BOTSIDnr": "1",
                }
            }
        ],
    }

    # 2. Serialize to JSON
    json_str = json.dumps(original_ast)

    # 3. Deserialize back to Node and verify
    data = json.loads(json_str)
    node = Node.from_dict(data)

    assert node.record["BOTSID"] == "UNB"
    assert len(node.children) == 1
    assert node.children[0].record["S009.0065"] == "ORDERS"

    # We won't test `edi_to_json` with a real file here unless we provide a real grammar.
    # But we can test `to_dict` works on the restored node.
    restored_ast = node.to_dict()
    assert restored_ast == original_ast


def test_generate_997():
    from bots_core.facade import generate_997_ast

    # Simulate an incoming X12 AST with GS
    in_ast = {
        "record": {"BOTSID": "ISA", "ISA13": "000000001"},
        "children": [
            {
                "record": {"BOTSID": "GS", "GS01": "PO", "GS06": "123456"},
                "children": [{"record": {"BOTSID": "ST", "ST01": "850", "ST02": "0001"}}],
            }
        ],
    }

    in_json = json.dumps(in_ast)
    ack_json = generate_997_ast(in_json, error_list=[])

    ack_ast = json.loads(ack_json)

    # Ensure the root of the generated AST is ST for 997
    assert ack_ast["record"]["BOTSID"] == "ST"
    assert ack_ast["record"]["ST01"] == "997"

    # Check children: AK1, AK9, SE
    children = ack_ast["children"]
    assert len(children) == 3

    ak1 = children[0]["record"]
    assert ak1["BOTSID"] == "AK1"
    assert ak1["AK101"] == "PO"
    assert ak1["AK102"] == "123456"

    ak9 = children[1]["record"]
    assert ak9["BOTSID"] == "AK9"
    assert ak9["AK901"] == "A"  # No errors

    se = children[2]["record"]
    assert se["BOTSID"] == "SE"
