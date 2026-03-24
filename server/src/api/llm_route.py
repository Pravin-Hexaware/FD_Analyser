from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

from service.analysis_service import analyze_target_companies_from_query

router = APIRouter()


class LLMQueryRequest(BaseModel):
    query: str


@router.post("/llm/target_companies", response_model=Dict[str, Any])
async def llm_target_companies(request: LLMQueryRequest):
    """Parse user query to target companies + two peers each with Azure LLM."""
    try:
        result = analyze_target_companies_from_query(request.query)
        parsed = result.get("parsed") if isinstance(result, dict) else None
        if isinstance(parsed, dict) and parsed.get("error"):
            raise HTTPException(status_code=500, detail=parsed.get("error"))

        if not isinstance(parsed, dict):
            raise HTTPException(status_code=500, detail="LLM did not return a parsed JSON object")

        # Return only the main JSON structure, as requested.
        return parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
