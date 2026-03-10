from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from service.html_extraction_service import extract_html_data
from service.xml_extraction_service import extract_xbrl_data
from repository.html_data_repository import HTMLDataRepository
from repository.xml_data_repository import XMLDataRepository

router = APIRouter()

class ExtractXBRLRequest(BaseModel):
    url: List[str]

class ExtractXBRLResponse(BaseModel):
    response: List[Dict[str, Any]]

@router.post("/extract/urls", response_model=ExtractXBRLResponse)
async def extract_xbrl(request: ExtractXBRLRequest):
    """
    Extract XBRL data from multiple URLs.
    If URL ends with .xml, treat as XML XBRL; otherwise treat as HTML iXBRL.
    Expects JSON payload: {"url": ["https://...", "https://..."]}
    Returns JSON with extracted data for each URL.
    """

    if not request.url:
        raise HTTPException(status_code=400, detail="No URLs provided")

    response = []

    for url in request.url:
        try:
            if url.endswith(".xml"):
                # Extract XML XBRL data
                only_prefix = "in-bse-fin"  # You can make this configurable if needed
                extracted_data = extract_xbrl_data(url, only_prefix)

                # Save to files
                repo = XMLDataRepository()
                json_path = repo.save_to_json(extracted_data)
                csv_path = repo.save_to_csv(extracted_data)

                response.append({
                    "url": url,
                    "type": "xml",
                    "count": len(extracted_data),
                    "data": extracted_data,
                    "files": {
                        "json": json_path,
                        "csv": csv_path
                    }
                })

            elif url.endswith((".html", ".htm", ".xhtml")):
                # Extract HTML iXBRL data
                extracted_data = extract_html_data(url)

                # Save to files
                repo = HTMLDataRepository()
                json_path = repo.save_to_json(extracted_data)
                csv_path = repo.save_to_csv(extracted_data)

                response.append({
                    "url": url,
                    "type": "html",
                    "count": len(extracted_data),
                    "data": extracted_data,
                    "files": {
                        "json": json_path,
                        "csv": csv_path
                    }
                })

            else:
                # Unknown file type
                response.append({
                    "url": url,
                    "type": "unknown",
                    "error": "Unsupported file extension. Supported: .xml, .html, .htm, .xhtml"
                })

        except Exception as e:
            response.append({
                "url": url,
                "error": str(e)
            })

    return ExtractXBRLResponse(response=response)        
        