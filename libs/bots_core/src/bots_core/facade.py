import json
import os
import tempfile

from bots_core.domain import inmessage, outmessage
from bots_core.domain.node import Node
from bots_core.domain.x12_ack import generate_997_ast as internal_generate_997
from bots_core.infrastructure.config.botsconfig import OK


def edi_to_json(edi_file_path: str, editype: str, messagetype: str) -> str:
    """
    Parses an EDI file against its Grammar and returns a stateless JSON string.

    :param edi_file_path: Absolute path to the raw EDI file.
    :param editype: The standard (e.g., 'edifact', 'x12').
    :param messagetype: The specific transaction type (e.g., 'ORDERS', '850').
    :return: A JSON string representing the parsed Node AST.
    """
    edifile = inmessage.parse_edi_file(
        filename=edi_file_path,
        editype=editype,
        messagetype=messagetype,
        frompartner="",
        topartner="",
        testindicator="",
        charset="",
        alt="",
        fromchannel="",
        idroute="",
        command="",
    )
    edifile.checkforerrorlist()

    # Depending on if it's multiple messages, `root.children` holds them.
    # The `Node` tree correctly encapsulates the entire file.
    ast_dict = edifile.root.to_dict()
    return json.dumps(ast_dict, indent=2)


def json_to_edi(
    json_ast: str,
    editype: str,
    messagetype: str,
    output_file_path: str | None = None,
) -> str:
    """
    Generates a raw EDI string from a stateless JSON dictionary.

    :param json_content: JSON string representing the Node AST.
    :param editype: The standard (e.g., 'edifact', 'x12').
    :param messagetype: The specific transaction type (e.g., 'ORDERS', '850').
    :param output_file_path: Optional path to write the output. If not provided, returns the EDI string.
    :return: The generated raw EDI string (if output_file_path is None).
    """
    data = json.loads(json_ast)
    root_node = Node.from_dict(data)

    is_temp = output_file_path is None
    if is_temp:
        from bots_core.utils.botslib import botsglobal

        data_dir = botsglobal.ini.get("directories", "data")
        fd, output_file_path = tempfile.mkstemp(suffix=".edi", dir=data_dir or None)
        os.close(fd)

    try:
        out = outmessage.outmessage_init(
            editype=editype,
            messagetype=messagetype,
            filename=output_file_path,
            reference="1",
            statust=OK,
            divtext="",
        )
        out.root = root_node
        out.writeall()

        if is_temp:
            with open(output_file_path, encoding=out.ta_info.get("charset", "utf-8")) as f:
                return f.read()
        return ""
    finally:
        if is_temp and os.path.exists(output_file_path):
            os.remove(output_file_path)


def generate_997_ast(inmessage_ast: str, error_list: list[str] | None = None) -> str:
    """
    Generates a stateless 997 Functional Acknowledgment JSON AST from an incoming X12 JSON AST.

    :param inmessage_ast: The incoming JSON AST (as a string) to acknowledge.
    :param error_list: Optional list of errors to append.
    :return: The generated 997 Functional Acknowledgment JSON AST as a string.
    """
    data = json.loads(inmessage_ast)
    root_node = Node.from_dict(data)

    ack_node = internal_generate_997(root_node, error_list)
    return json.dumps(ack_node.to_dict(), indent=2)
