"""Annual XBRL extraction from URLs."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator

from services.html_extraction_service import extract_html_data
from services.xml_extraction_service import extract_xbrl_data
from services.xbrl_metrics_service import calculate_metrics_fourd, convert_xml_grouped_to_list


class ExtractAnnualRequest(BaseModel):
    url: List[str]

    @field_validator("url", mode="before")
    @classmethod
    def convert_url_to_list(cls, v):
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return v
        raise ValueError("url must be a string or list of strings")


async def extract_annual(request: ExtractAnnualRequest) -> Dict[str, Any]:
    """Extract annual metrics from one or more XBRL/iXBRL URLs."""
    results = []
    errors = []

    for url in request.url:
        try:
            if url.lower().endswith((".xml", ".xbrl")):
                grouped = extract_xbrl_data(url)
                flat = convert_xml_grouped_to_list(grouped)
                extraction_type = "xml"
            else:
                flat = extract_html_data(url)
                extraction_type = "html"

            metrics = calculate_metrics_fourd(flat)
            results.append({
                "url": url,
                "type": extraction_type,
                **metrics,
            })
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)})

    if not results and errors:
        return {"error": errors[0]["error"], "details": errors}

    return {
        "results": results,
        "errors": errors,
        "count": len(results),
    }
