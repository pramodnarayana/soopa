import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from transformer.domain.exceptions import TranslationError
from transformer.infrastructure.adapters.bots_adapter import BotsEDIAdapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/edi-tools", tags=["EDI Tools"])


class TransformRequest(BaseModel):
    action: str = Field(..., description="One of: EDI_TO_JSON, JSON_TO_EDI")
    payload: str = Field(..., description="The raw EDI or JSON payload to transform.")


class TransformResponse(BaseModel):
    result: str | None = None
    valid: bool = False
    error: str | None = None


async def _handle_edi_to_json(
    request: TransformRequest, adapter: BotsEDIAdapter
) -> TransformResponse:
    raw_bytes = request.payload.encode("utf-8")
    logger.info(f"EDI TOOL RECEIVED PAYLOAD LENGTH: {len(raw_bytes)}")

    # Delegate parsing and validation to the common BotsEDIAdapter
    ast_dict, errors = adapter.get_raw_ast(raw_bytes)

    # We embed validation errors into an API envelope wrapper
    # so the payload (ast) remains pristine and unpolluted.
    if errors:
        envelope = {"meta": {"valid": False, "validation_errors": errors}, "data": ast_dict}
        return TransformResponse(result=json.dumps(envelope, indent=2), valid=False)

    envelope = {"meta": {"valid": True, "validation_errors": []}, "data": ast_dict}
    return TransformResponse(result=json.dumps(envelope, indent=2), valid=True)


async def _handle_json_to_edi(
    request: TransformRequest, adapter: BotsEDIAdapter
) -> TransformResponse:
    payload_dict = json.loads(request.payload)
    # Smart Extractor: Strip the API Envelope if it exists
    if "data" in payload_dict and "meta" in payload_dict:
        ast_dict = payload_dict["data"]
    else:
        ast_dict = payload_dict

    # Delegate EDI serialization to the common BotsEDIAdapter
    # We assume X12 by default for now, but this could be inferred
    # from the AST (e.g. presence of interchange_UNB)
    standard = "x12"
    if "interchange_UNB" in ast_dict or (
        isinstance(ast_dict, list) and len(ast_dict) > 0 and "interchange_UNB" in ast_dict[0]
    ):
        standard = "edifact"

    edi_str, errors = adapter.serialize_to_edi(ast_dict, standard=standard)

    # Filter out warnings
    fatal_errors = [e for e in errors if not e.startswith("[W")]

    if fatal_errors:
        return TransformResponse(result=edi_str, valid=False, error="\n".join(fatal_errors))

    return TransformResponse(result=edi_str, valid=True)


@router.post("/transform", response_model=TransformResponse)
async def transform_payload(request: TransformRequest) -> TransformResponse:
    handlers = {
        "EDI_TO_JSON": _handle_edi_to_json,
        "JSON_TO_EDI": _handle_json_to_edi,
    }

    handler = handlers.get(request.action)
    if not handler:
        raise HTTPException(status_code=400, detail="Invalid action provided.")

    try:
        adapter = BotsEDIAdapter()
        return await handler(request, adapter)

    except TranslationError as e:
        logger.exception("Translation error in EDI tool")

        # If the AST generation completely crashed (e.g. fatal syntax error),
        # get_raw_ast will still raise TranslationError
        if e.errors:
            structured_error = {"status": "fatal_validation_failed", "errors": e.errors}
            return TransformResponse(
                result=None, valid=False, error=json.dumps(structured_error, indent=2)
            )

        return TransformResponse(
            result=None,
            valid=False,
            error=json.dumps({"status": "system_error", "message": str(e)}, indent=2),
        )

    except Exception as e:
        logger.exception("Transformation failed")
        error_msg = str(e)

        # Fallback for unexpected system errors
        return TransformResponse(
            result=None,
            valid=False,
            error=json.dumps({"status": "system_error", "message": error_msg}, indent=2),
        )
