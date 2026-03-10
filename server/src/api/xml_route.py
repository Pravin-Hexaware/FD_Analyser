from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from service.xml_extraction_service import extract_xbrl_data
from repository.xml_data_repository import XMLDataRepository

router = APIRouter()

class ExtractRequest(BaseModel):
    url: str

class ExtractResponse(BaseModel):
    count: int
    data: List[Dict[str, Any]]
    files: Dict[str, str]

@router.post("/extract/xml", response_model=ExtractResponse)
async def extract_xml(request: ExtractRequest):
    """
    Extract XBRL data from a URL.
    Expects JSON payload: {"url": "https://...", "only_prefix": "optional_prefix"}
    Returns JSON with extracted data.
    """
    try:
        only_prefix="in-bse-fin"
        extracted_data = extract_xbrl_data(request.url,only_prefix)

        # Optionally save to files
        repo = XMLDataRepository()
        json_path = repo.save_to_json(extracted_data)
        csv_path = repo.save_to_csv(extracted_data)

        return ExtractResponse(
            count=len(extracted_data),
            data=extracted_data,
            files={
                "json": json_path,
                "csv": csv_path
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))