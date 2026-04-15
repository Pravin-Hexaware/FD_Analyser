"""API routes for managing missing companies."""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import csv
from pathlib import Path
from datetime import datetime
from repository.sqlite_repository import SqliteRepository

router = APIRouter()


def _missing_tracker_csv_path() -> Path:
    """Get path to missing_companies.csv"""
    src_dir = Path(__file__).resolve().parents[1]   # points to src/
    data_dir = src_dir / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "missing_companies.csv"


def _company_metadata_csv_path() -> Path:
    """Get path to Company_metadata.csv (BSE Filings)"""
    src_dir = Path(__file__).resolve().parents[1]   # points to src/
    data_dir = src_dir / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "Company_metadata.csv"


def get_company_filing_count(scrip_code: str) -> int:
    """
    Get count of XBRL filings for a company in the database.
    Returns 0 if no filings found.
    """
    try:
        db = SqliteRepository()
        conn = db._conn
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM xbrl_filing_table WHERE scrip_code = ?
        ''', (scrip_code,))
        
        result = cursor.fetchone()
        return result[0] if result else 0
    except Exception as e:
        print(f"[ERROR] Failed to get filing count for {scrip_code}: {e}")
        return 0


def has_filings(scrip_code: str) -> bool:
    """Check if company has any XBRL filings in database."""
    return get_company_filing_count(scrip_code) > 0


def add_companies_to_bse_metadata(scrip_codes: List[str]) -> Dict[str, Any]:
    """
    Add missing companies to Company_metadata.csv (BSE Filings data source) AND to database.
    Returns success count and any errors.
    """
    missing_companies = get_missing_companies_data()
    metadata_path = _company_metadata_csv_path()
    
    # Filter to only selected companies
    scrip_codes_set = {s.strip().lower() for s in scrip_codes}
    companies_to_add = [
        c for c in missing_companies
        if c['scrip_code'].strip().lower() in scrip_codes_set
    ]
    
    if not companies_to_add:
        return {
            "success": False,
            "message": "No matching companies found in missing list",
            "added_count": 0,
            "errors": []
        }
    
    added_count = 0
    errors = []
    
    try:
        # Initialize database
        db = SqliteRepository()
        
        # Read existing metadata
        existing_companies = {}
        if metadata_path.exists():
            with open(metadata_path, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    for row in reader:
                        scrip = (row.get('Scrip-code') or '').strip()
                        if scrip:
                            existing_companies[scrip.lower()] = row
        
        # Add new companies to CSV and database
        for company in companies_to_add:
            scrip_code = company['scrip_code'].strip()
            
            # Skip if already exists
            if scrip_code.lower() in existing_companies:
                errors.append(f"{company['company_name']} already exists in BSE metadata")
                continue
            
            # Prepare row with same format as Company_metadata.csv
            new_row = {
                'Company': company['company_name'],
                'Symbol': company['symbol'],
                'Scrip-code': scrip_code,
                'Sector ': '',  # Note: BSE metadata has space in header
                'Industry': ''
            }
            existing_companies[scrip_code.lower()] = new_row
            
            # Add to database
            try:
                conn = db._conn
                cursor = conn.cursor()
                
                # Check if company already exists in database
                cursor.execute('''
                    SELECT id FROM company_table WHERE scrip_code = ?
                ''', (scrip_code,))
                
                if not cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO company_table 
                        (company_name, symbol, scrip_code, sector, industry) 
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        company['company_name'],
                        company['symbol'],
                        scrip_code,
                        '',  # sector
                        ''   # industry
                    ))
                    conn.commit()
                else:
                    errors.append(f"{company['company_name']} already exists in database")
            except Exception as db_error:
                print(f"[ERROR] Failed to add {company['company_name']} to database: {db_error}")
                errors.append(f"Database error for {company['company_name']}: {str(db_error)}")
                continue
            
            added_count += 1
        
        # Write back to metadata CSV
        if metadata_path.exists() or added_count > 0:
            fieldnames = ['Company', 'Symbol', 'Scrip-code', 'Sector ', 'Industry']
            with open(metadata_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for scrip_code, row in sorted(existing_companies.items()):
                    # Ensure all fields exist
                    for field in fieldnames:
                        if field not in row:
                            row[field] = ''
                    writer.writerow({k: row.get(k, '') for k in fieldnames})
        
        # Remove added companies from missing list
        for company in companies_to_add:
            if added_count > 0:  # Only remove if actually added
                _remove_missing_company_internal(company['scrip_code'])
        
        return {
            "success": True,
            "message": f"Added {added_count} companies to BSE Filings and database",
            "added_count": added_count,
            "errors": errors
        }
        
    except Exception as e:
        print(f"[ERROR] Adding companies to metadata: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": str(e),
            "added_count": 0,
            "errors": [str(e)]
        }


def _remove_missing_company_internal(scrip_code: str) -> bool:
    """Internal function to remove company from missing CSV."""
    csv_path = _missing_tracker_csv_path()
    
    if not csv_path.exists():
        return False
    
    try:
        records = []
        with open(csv_path, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for row in reader:
                if row.get('scrip_code', '').strip() != scrip_code.strip():
                    records.append(row)
        
        if fieldnames:
            with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(records)
        
        return True
    except Exception as e:
        print(f"[ERROR] Removing missing company: {e}")
        return False


def get_missing_companies_data() -> List[Dict[str, Any]]:
    """Read missing companies from CSV file."""
    try:
        csv_path = _missing_tracker_csv_path()
        
        if not csv_path.exists():
            return []
        
        missing_companies = []
        with open(csv_path, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            
            if not fieldnames:
                return []
            
            for row in reader:
                if row.get('company_name') and row.get('company_name').strip():
                    company_data = {
                        'timestamp': row.get('timestamp', ''),
                        'company_name': row.get('company_name', '').strip(),
                        'symbol': row.get('symbol', '').strip(),
                        'scrip_code': row.get('scrip_code', '').strip(),
                        'frequency': row.get('frequency', 'quarterly'),
                        'period': row.get('period', 'unspecified'),
                        'time_horizon': row.get('time_horizon', 'unspecified'),
                        'is_peer': row.get('is_peer', 'false').lower() == 'true',
                        'query': row.get('query', ''),
                    }
                    missing_companies.append(company_data)
        
        return missing_companies
        
    except Exception as e:
        print(f"[ERROR] Exception in get_missing_companies_data: {e}")
        import traceback
        traceback.print_exc()
        return []


class MissingCompany(BaseModel):
    """Represents a missing company from CSV."""
    timestamp: str
    company_name: str
    symbol: str
    scrip_code: str
    frequency: str
    period: str
    time_horizon: str
    is_peer: bool
    query: str


class ProcessMissingCompanyRequest(BaseModel):
    """Request to process a missing company."""
    scrip_codes: Optional[List[str]] = None  # If None, process all


class MissingCompanyProcessResult(BaseModel):
    """Result of processing a missing company."""
    scrip_code: str
    company_name: str
    xbrl_url: Optional[str] = None
    period: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    duration_ms: int = 0


class ProcessMissingCompaniesResponse(BaseModel):
    """Response from batch processing missing companies."""
    total: int
    processed: int
    timestamp: str
    results: List[MissingCompanyProcessResult]


@router.get("/missing-companies")
async def get_missing_companies():
    """
    Get all missing companies from CSV file.
    These are companies that were requested but not found in the database.
    Admin can then initiate XBRL fetching for these companies.
    """
    try:
        missing_companies = get_missing_companies_data()
        return missing_companies
    except Exception as e:
        print(f"[ERROR] Exception in get_missing_companies endpoint: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/missing-companies/status")
async def get_missing_companies_status():
    """
    Get all missing companies with their filing status.
    Returns which ones have filings already fetched and which need fetching.
    """
    try:
        missing_companies = get_missing_companies_data()
        
        # Enrich with filing status
        companies_with_status = []
        for company in missing_companies:
            scrip_code = company.get('scrip_code', '')
            filing_count = get_company_filing_count(scrip_code)
            
            companies_with_status.append({
                **company,
                'has_filings': filing_count > 0,
                'filing_count': filing_count,
                'needs_fetching': filing_count == 0
            })
        
        print(f"[DEBUG] Returning {len(companies_with_status)} missing companies with status")
        return companies_with_status
    except Exception as e:
        print(f"[ERROR] Exception in get_missing_companies_status endpoint: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/missing-companies/add-to-bse")
async def add_missing_to_bse(request: ProcessMissingCompanyRequest):
    """
    Add selected missing companies to BSE Filings data source (Company_metadata.csv).
    After adding, admin can process them using the normal XBRL extraction WebSocket.
    
    Request body:
    {
        "scrip_codes": ["500124", "543210"]
    }
    """
    try:
        if not request.scrip_codes or len(request.scrip_codes) == 0:
            raise HTTPException(status_code=400, detail="No companies selected")
        
        result = add_companies_to_bse_metadata(request.scrip_codes)
        
        if result["success"]:
            return {
                "success": True,
                "message": result["message"],
                "added_count": result["added_count"],
                "errors": result["errors"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["message"])
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Error adding to BSE metadata: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/missing-companies/process", response_model=ProcessMissingCompaniesResponse)
async def process_missing_companies(
    request: ProcessMissingCompanyRequest,
    background_tasks: BackgroundTasks
):
    """
    Process missing companies: fetch XBRL URLs for them.
    
    Request body:
    {
        "scrip_codes": ["500124", "543210"] or null (for all)
    }
    
    This endpoint will:
    1. Fetch XBRL URLs using the existing batch_xbrl_finder endpoint
    2. Return results for each company
    3. Remove successfully processed companies from the missing_companies.csv
    """
    try:
        from api.service.missing_company_service import MissingCompanyService
        result = await MissingCompanyService.process_missing_companies_batch(
            scrip_codes=request.scrip_codes
        )
        return result
    except Exception as e:
        print(f"[ERROR] Error processing missing companies: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error processing missing companies: {str(e)}")


@router.post("/missing-companies/{scrip_code}/remove")
async def remove_missing_company(scrip_code: str):
    """
    Remove a specific company from the missing_companies.csv file.
    Called after manually processing or if company is already in database.
    """
    try:
        from api.service.missing_company_service import MissingCompanyService
        success = MissingCompanyService.remove_missing_company(scrip_code)
        if success:
            return {"success": True, "message": f"Removed {scrip_code} from missing companies list"}
        else:
            raise HTTPException(status_code=404, detail=f"Company {scrip_code} not found in missing list")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/missing-companies/count")
async def get_missing_companies_count():
    """Get count of missing companies awaiting processing."""
    try:
        missing = get_missing_companies_data()
        return {
            "count": len(missing),
            "last_updated": missing[0].get('timestamp') if missing else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
