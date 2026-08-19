"""API routes for managing missing companies."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from services.missing_companies_admin_service import MissingCompaniesAdminService

router = APIRouter()
_admin_service = MissingCompaniesAdminService()


class ProcessMissingCompanyRequest(BaseModel):
    scrip_codes: Optional[List[str]] = None


@router.get("/missing-companies")
async def get_missing_companies():
    try:
        return _admin_service.get_missing_companies()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/missing-companies/status")
async def get_missing_companies_status():
    try:
        return _admin_service.get_missing_companies_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/missing-companies/add-to-bse")
async def add_missing_to_bse(request: ProcessMissingCompanyRequest):
    try:
        if not request.scrip_codes:
            raise HTTPException(status_code=400, detail="No companies selected")

        result = _admin_service.add_companies_to_bse_metadata(request.scrip_codes)
        if result["success"]:
            return {
                "success": True,
                "message": result["message"],
                "added_count": result["added_count"],
                "errors": result["errors"],
            }
        raise HTTPException(status_code=400, detail=result["message"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
