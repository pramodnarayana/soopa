import json
import re

from bots_core.domain import inmessage, outmessage
from bots_core.domain.node import Node
from bots_core.domain.x12_ack import generate_997_ast as internal_generate_997


def edi_to_json(
    editype: str,
    messagetype: str,
    edi_file_path: str | None = None,
    raw_edi: bytes | str | None = None,
    return_errors: bool = False,
) -> str:
    """
    Parses an EDI file against its Grammar and returns a stateless JSON string.
    You must provide either edi_file_path OR raw_edi.

    :param editype: The standard (e.g., 'edifact', 'x12').
    :param messagetype: The specific transaction type (e.g., 'envelope', 'ORDERS', '850').
    :param edi_file_path: Absolute path to the raw EDI file.
    :param raw_edi: The raw EDI content in memory as bytes or string.
    :param return_errors: If True, returns a dict with 'ast' and 'errors'.
    :return: A JSON string representing the parsed Node AST.
    """
    if edi_file_path is None and raw_edi is None:
        raise ValueError("Must provide either edi_file_path or raw_edi")

    ta_info = dict(
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

    if raw_edi is not None:
        ta_info["raw_edi"] = raw_edi
    else:
        ta_info["filename"] = edi_file_path

    edifile = inmessage.parse_edi_file(**ta_info)

    if edifile.root is None:
        error_msg = (
            "\n".join(edifile.errorlist) if edifile.errorlist else "Parsing failed completely."
        )
        raise ValueError(
            f"Invalid format: Could not generate an AST. Ensure the payload matches the expected input format (e.g. not passing JSON into an EDI parser).\nDetails: {error_msg}"
        )

    ast_dict = edifile.root.to_dict()

    if return_errors:
        return json.dumps({"ast": ast_dict, "errors": edifile.errorlist}, indent=2)

    edifile.checkforerrorlist()
    return json.dumps(ast_dict, indent=2)


def json_to_edi(
    json_ast: str,
    editype: str,
    messagetype: str,
    output_file_path: str | None = None,
    return_errors: bool = False,
) -> str:
    """
    Takes a JSON string representing a parsed AST and writes/returns raw EDI format.

    :param json_ast: A JSON string of the Node AST.
    :param editype: The standard (e.g., 'edifact', 'x12').
    :param messagetype: The specific transaction type (e.g., 'ORDERS', '850').
    :param output_file_path: Optional file to write to.
    :param return_errors: If True, returns a dict with 'edi' and 'errors'.
    :return: A string of the generated EDI format (or JSON string if return_errors is True).
    """
    ast_dict = json.loads(json_ast)
    root_node = Node.from_dict(ast_dict)

    ta_info = {
        "editype": editype,
        "messagetype": messagetype,
        "charset": "utf-8",
        "checkcharsetout": "strict",
        "merge": False,
        "ignore_out_errors": return_errors,
    }

    if output_file_path:
        ta_info["filename"] = output_file_path
    else:
        ta_info["return_string"] = True

    try:
        out = outmessage.outmessage_init(**ta_info)
        out.root = root_node
        out.writeall()

        if output_file_path:
            # If written to file, read it back for the return value
            with open(output_file_path, encoding="utf-8") as f:
                result = f.read()
        else:
            result = out.ta_info.get("output_string", "")

        # Ensure X12 ISA fixed-length structural integrity
        if editype == "x12" and result.startswith("ISA"):
            field_sep = out.ta_info.get("field_sep", "*")
            sfield_sep = out.ta_info.get("sfield_sep", ">")
            record_sep = out.ta_info.get("record_sep", "~")

            isa_end_idx = result.find(record_sep)
            if isa_end_idx != -1:
                isa_segment = result[:isa_end_idx]
                elements = isa_segment.split(field_sep)
                # X12 ISA requires exactly 16 field separators (17 elements when split)
                if len(elements) < 17:
                    # Pad missing empty trailing elements (like ISA16)
                    padding_needed = 17 - len(elements)
                    padding = (field_sep * padding_needed) + sfield_sep
                    # Notice: ISA16 value is effectively the sfield_sep character itself

                    isa_segment = isa_segment + padding
                    result = isa_segment + result[isa_end_idx:]

                    if not hasattr(out, "errorlist"):
                        out.errorlist = []
                    out.errorlist.append(
                        "[W01]: Auto-injected missing ISA16 (component separator) to maintain strict X12 ISA fixed-length structural integrity.\n"
                    )

        if return_errors:
            errors = list(out.errorlist) if hasattr(out, "errorlist") else []
            # Run strict inbound validation to catch envelope errors (e.g. SE segment counts)
            if result:
                try:
                    validation_result = edi_to_json(
                        editype=editype,
                        messagetype=messagetype,
                        raw_edi=result.encode("utf-8"),
                        return_errors=True,
                    )
                    inbound_errors = json.loads(validation_result).get("errors", [])

                    def normalize_error(err_str):
                        # Strip " line X" and " pos Y" from the error to allow deduplication
                        err_str = re.sub(r" line \d+", "", err_str)
                        err_str = re.sub(r" pos \d+", "", err_str)
                        return err_str

                    normalized_existing = {normalize_error(e) for e in errors}

                    for err in inbound_errors:
                        norm_err = normalize_error(err)
                        if norm_err not in normalized_existing:
                            errors.append(err)
                            normalized_existing.add(norm_err)
                except ValueError as e:
                    # If it completely fails to parse, extract the error message
                    err_msg = str(e)
                    if "Details: " in err_msg:
                        err_msg = err_msg.split("Details: ")[1]
                    if err_msg not in errors:
                        errors.append(err_msg)
                except Exception as e:
                    if str(e) not in errors:
                        errors.append(str(e))
            return json.dumps({"edi": result, "errors": errors}, indent=2)
        return result
    except Exception as e:
        if return_errors and "out" in locals():
            # If the engine completely crashed but we want errors, return them alongside whatever was produced
            result = out.ta_info.get("output_string", "")
            errors = out.errorlist if (hasattr(out, "errorlist") and out.errorlist) else [str(e)]
            return json.dumps({"edi": result, "errors": errors}, indent=2)
        raise RuntimeError(f"Failed to generate EDI: {e}") from e


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
