import asyncio
import json
from enum import StrEnum
from typing import cast

import structlog
from edi.domain.exceptions import EdiTransformationError, OrchestrationError
from edi.domain.transaction.enums import EdiStandard
from edi.ports.outbound.edi_ast_codec_port import EdiAstCodecPort
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from seedwork.domain.types import JsonDict

from unified_api.adapters.inbound.http.dependencies.edi.services import get_edi_ast_codec

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/edi-tools", tags=["EDI Tools"])


class TransformAction(StrEnum):
    EDI_TO_JSON = "EDI_TO_JSON"
    JSON_TO_EDI = "JSON_TO_EDI"


class TransformRequest(BaseModel):
    action: TransformAction = Field(..., description="One of: EDI_TO_JSON, JSON_TO_EDI")
    payload: str = Field(..., description="The raw EDI or JSON payload to transform.")


class TransformResponse(BaseModel):
    result: str | None = None
    valid: bool = False
    error: str | None = None


async def _handle_edi_to_json(
    request: TransformRequest, codec: EdiAstCodecPort
) -> TransformResponse:
    raw_bytes = request.payload.encode("utf-8")
    logger.info("edi_tool.received_payload", payload_length=len(raw_bytes))

    ast_dict, errors = await asyncio.to_thread(codec.get_raw_ast, raw_bytes)

    if errors:
        envelope = {"meta": {"valid": False, "validation_errors": errors}, "data": ast_dict}
        return TransformResponse(result=json.dumps(envelope, indent=2), valid=False)

    envelope = {"meta": {"valid": True, "validation_errors": []}, "data": ast_dict}
    result_str = json.dumps(envelope, indent=2)
    logger.info("edi_tool.success", ast_keys=list(ast_dict.keys()), result_length=len(result_str))
    return TransformResponse(result=result_str, valid=True)


async def _handle_json_to_edi(
    request: TransformRequest, codec: EdiAstCodecPort
) -> TransformResponse:
    payload_dict = json.loads(request.payload)

    raw_ast = (
        payload_dict["data"]
        if isinstance(payload_dict, dict) and "data" in payload_dict and "meta" in payload_dict
        else payload_dict
    )

    if not isinstance(raw_ast, (dict, list)):
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload structure. Must be an object or a list of objects.",
        )

    if isinstance(raw_ast, list) and not all(isinstance(item, dict) for item in raw_ast):
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload structure. Every element of the list must be an object.",
        )

    ast_dict = cast("JsonDict | list[JsonDict]", raw_ast)

    standard = EdiStandard.X12
    if "interchange_UNB" in ast_dict or (
        isinstance(ast_dict, list) and len(ast_dict) > 0 and "interchange_UNB" in ast_dict[0]
    ):
        standard = EdiStandard.EDIFACT

    edi_str, errors = await asyncio.to_thread(codec.serialize_to_edi, ast_dict, standard=standard)

    fatal_errors = [e for e in errors if not e.startswith("[W")]

    if fatal_errors:
        return TransformResponse(result=edi_str, valid=False, error="\n".join(fatal_errors))

    return TransformResponse(result=edi_str, valid=True)


@router.post("/transform", response_model=TransformResponse)
async def transform_payload(
    request: TransformRequest,
    codec: EdiAstCodecPort = Depends(get_edi_ast_codec),
) -> TransformResponse:
    handlers = {
        TransformAction.EDI_TO_JSON: _handle_edi_to_json,
        TransformAction.JSON_TO_EDI: _handle_json_to_edi,
    }

    handler = handlers.get(request.action)
    if not handler:
        raise HTTPException(status_code=400, detail="Invalid action provided.")

    try:
        return await handler(request, codec)

    except EdiTransformationError as e:
        if e.errors:
            logger.info("edi_tool.validation_failed", errors=e.errors)
            structured_error = {"status": "fatal_validation_failed", "errors": e.errors}
            return TransformResponse(
                result=None, valid=False, error=json.dumps(structured_error, indent=2)
            )

        logger.exception("edi_tool.system_error")
        return TransformResponse(
            result=None,
            valid=False,
            error=json.dumps({"status": "system_error", "message": str(e)}, indent=2),
        )

    except json.JSONDecodeError as e:
        logger.exception("JSON decoding failed")
        return TransformResponse(
            result=None,
            valid=False,
            error=json.dumps({"status": "invalid_json", "message": str(e)}, indent=2),
        )

    except OrchestrationError as e:
        logger.exception("Transformation failed")
        error_msg = str(e)

        return TransformResponse(
            result=None,
            valid=False,
            error=json.dumps({"status": "system_error", "message": error_msg}, indent=2),
        )
