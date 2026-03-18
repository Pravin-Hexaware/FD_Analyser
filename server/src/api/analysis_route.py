from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from service.analysis_service import generate_analysis_report, test_llm_connection

router = APIRouter()


class AnalysisResponse(BaseModel):
    report: str
    llm_response: Optional[Dict[str, Any]] = None


@router.post("/analysis", response_model=AnalysisResponse)
async def analyze_financials(items: List[Dict[str, Any]] = Body(...)):
    """Generate a financial analysis report from a list of company records.

    The request body must be an array of objects (dictionaries). Each object can contain
    any fields; the endpoint simply forwards the data to the LLM for analysis.
    """
    try:
        report, raw = generate_analysis_report(items)
        return AnalysisResponse(report=report, llm_response=raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analysis/test")
async def analysis_test():
    """Quick health check: verify the LLM deployment can return a non-empty response."""
    try:
        return test_llm_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
