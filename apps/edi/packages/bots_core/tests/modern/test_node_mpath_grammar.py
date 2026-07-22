import pytest
from bots_core.domain.exceptions import MappingFormatError
from bots_core.domain.models import create_field_definition, create_structure_node
from bots_core.domain.node import Node


def test_node_mpath_grammar_check():
    # Setup node with grammar
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})

    # Create grammar structure
    # ROOT -> LEVEL 1: CHILD -> LEVEL 2: GRANDCHILD
    root_recorddefs = [
        [
            "BOTSID",
            "M",
            3,
            "AN",
            True,
            0,
            3,
            "AN",
            1,
        ],
        [
            "F1",
            "M",
            3,
            "AN",
            True,
            0,
            3,
            "AN",
            1,
        ],
        ["COMP1", "M", [["SUB1", "M", 3, "AN", True, 0, 0, "AN", 1]], "AN", False, 0, 0, "AN", 1],
    ]
    child_recorddefs = [
        ["BOTSID", "M", 3, "AN", True, 0, 3, "AN", 1],
    ]

    root_recorddefs = [create_field_definition(f) for f in root_recorddefs]
    child_recorddefs = [create_field_definition(f) for f in child_recorddefs]

    # [id, min_occ, max_occ, level, unknown, record_definition, structure/level]
    child_structure = create_structure_node(
        {0: "CHILD", 1: 0, 2: 99, 3: 0, 4: 0, 6: child_recorddefs, 9: "1"}
    )

    root_structure = create_structure_node(
        {0: "ROOT", 1: 0, 2: 99, 3: 0, 4: [child_structure], 6: root_recorddefs, 9: "1"}
    )

    node.structure = root_structure

    # 1. Valid mpath
    # BOTSIDnr is ignored
    # ROOT exists
    # F1 is a field
    # SUB1 is a subfield in COMP1 composite
    node._mpath_grammar_check(
        [
            {"BOTSID": "ROOT", "BOTSIDnr": "1", "F1": "VAL", "SUB1": "VAL2"},
            {"BOTSID": "CHILD", "BOTSIDnr": "1"},
        ]
    )

    # 2. Invalid field in ROOT
    with pytest.raises(MappingFormatError):
        node._mpath_grammar_check([{"BOTSID": "ROOT", "BOTSIDnr": "1", "INVALID": "VAL"}])

    # 3. Invalid field in CHILD
    with pytest.raises(MappingFormatError):
        node._mpath_grammar_check(
            [
                {"BOTSID": "ROOT", "BOTSIDnr": "1"},
                {"BOTSID": "CHILD", "BOTSIDnr": "1", "INVALID": "VAL"},
            ]
        )

    # 4. Unknown level
    with pytest.raises(MappingFormatError):
        node._mpath_grammar_check(
            [{"BOTSID": "ROOT", "BOTSIDnr": "1"}, {"BOTSID": "UNKNOWN", "BOTSIDnr": "1"}]
        )


def test_node_mpath_grammar_check_no_structure():
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})
    node.structure = None
    # Should just return without exception
    node._mpath_grammar_check([{"BOTSID": "ROOT", "BOTSIDnr": "1"}])
