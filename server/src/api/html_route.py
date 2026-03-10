from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from service.html_extraction_service import extract_html_data
from repository.html_data_repository import HTMLDataRepository

router = APIRouter()

class ExtractHTMLRequest(BaseModel):
    url: str

class ExtractHTMLResponse(BaseModel):
    count: int
    data: List[Dict[str, Any]]
    files: Dict[str, str]

@router.post("/extract/html", response_model=ExtractHTMLResponse)
async def extract_html(request: ExtractHTMLRequest):
    """
    Extract iXBRL data from an HTML URL.
    Expects JSON payload: {"url": "https://..."}
    Returns JSON with extracted data.
    """
    try:
        extracted_data = extract_html_data(request.url)

        # Optionally save to files
        repo = HTMLDataRepository()
        json_path = repo.save_to_json(extracted_data)
        csv_path = repo.save_to_csv(extracted_data)

        return ExtractHTMLResponse(
            count=len(extracted_data),
            data=extracted_data,
            files={
                "json": json_path,
                "csv": csv_path
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))