from edi.core.bots.domain.node import Node


def generate_997_ast(in_node: Node, error_list: list[str] | None = None) -> Node:
    """
    Generate a stateless 997 Functional Acknowledgment AST from an incoming X12 AST.

    :param in_node: The root Node of the parsed incoming X12 message.
    :param error_list: Optional list of errors encountered during parsing.
    :return: A new Node representing the root of the 997 message.
    """
    if error_list is None:
        error_list = []

    has_errors = len(error_list) > 0
    ack_code = "R" if has_errors else "A"

    # We assume the root node has ISA -> GS -> ST structures.
    # In BOTS, the root is typically a dummy node containing ISAs or the root itself is the message.

    # We will build the 997 AST.
    # Typically, an outgoing message needs a root node, then ST etc.
    # But for a full file, it needs ISA, GS, ST...
    # Since we are returning a stateless AST, we return the 997 transaction (ST to SE).
    # The pipeline can wrap it in ISA/GS later if needed, or we can generate the full envelope.

    root_997 = Node({"BOTSID": "ST", "ST01": "997", "ST02": "0001"})

    # Try to extract GS info from the incoming node.
    # In a full BOTS parse tree, we might have getloop("ISA", "GS")
    # For a stateless 997, we mainly need the GS reference to acknowledge.

    gs_node = None
    # Let's find the first GS node
    try:
        gs_node = next(in_node.getloop({"BOTSID": "ISA"}, {"BOTSID": "GS"}))
    except StopIteration:
        try:
            # Maybe the root is already GS?
            if in_node.record and in_node.record.get("BOTSID") == "GS":
                gs_node = in_node
            else:
                gs_node = next(in_node.getloop({"BOTSID": "GS"}))
        except StopIteration:
            pass

    if not gs_node:
        raise ValueError("Cannot generate 997: no GS segment found in input X12 message")

    ak1 = Node({"BOTSID": "AK1", "AK101": "", "AK102": ""})
    assert ak1.record is not None
    ak1.record["AK101"] = gs_node.get({"BOTSID": "GS", "GS01": None}) or "PO"
    ak1.record["AK102"] = gs_node.get({"BOTSID": "GS", "GS06": None}) or "1"

    root_997.append(ak1)

    # Optional: AK2/AK3/AK4 for transaction level details.
    # For a basic 997, we just need AK1 and AK9.

    # Count the actual number of ST transaction sets in the functional group
    st_count = 0
    try:
        for _st in in_node.getloop({"BOTSID": "ISA"}, {"BOTSID": "GS"}, {"BOTSID": "ST"}):
            st_count += 1
    except StopIteration:
        pass
    # If no ISA/GS/ST path, try direct GS/ST
    if st_count == 0:
        try:
            for _st in in_node.getloop({"BOTSID": "GS"}, {"BOTSID": "ST"}):
                st_count += 1
        except StopIteration:
            pass
    # Default to 1 if we couldn't find any
    if st_count == 0:
        st_count = 1

    ak9 = Node(
        {
            "BOTSID": "AK9",
            "AK901": ack_code,
            "AK902": str(st_count),  # Number of transaction sets included
            "AK903": str(st_count),  # Number of received transaction sets
            "AK904": str(st_count)
            if ack_code == "A"
            else "0",  # Number of accepted transaction sets
        }
    )

    root_997.append(ak9)

    se = Node({"BOTSID": "SE", "SE01": "4", "SE02": "0001"})
    root_997.append(se)

    return root_997
