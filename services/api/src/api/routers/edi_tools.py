import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
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


@router.post("/transform", response_model=TransformResponse)
async def transform_payload(request: TransformRequest) -> TransformResponse:
    try:
        adapter = BotsEDIAdapter()
        if request.action == "EDI_TO_JSON":
            raw_bytes = request.payload.encode("utf-8")
            logger.info(f"EDI TOOL RECEIVED PAYLOAD LENGTH: {len(raw_bytes)}")
            parsed_payload = await adapter.translate(raw_bytes)

            # For the tool, just return the first transaction or a list of them
            if not parsed_payload.transactions:
                return TransformResponse(result="{}", valid=True)

            json_ast = parsed_payload.transactions[0].data
            return TransformResponse(result=json.dumps(json_ast, indent=2), valid=True)

        elif request.action == "JSON_TO_EDI":
            # Reverse translation is not yet supported in this iteration
            return TransformResponse(result="JSON to EDI not yet implemented", valid=False)

        else:
            raise HTTPException(status_code=400, detail="Invalid action provided.")

    except Exception as e:
        logger.exception("Transformation failed")
        return TransformResponse(result=None, valid=False, error=str(e))
