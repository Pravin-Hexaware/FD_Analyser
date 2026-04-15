"""Service for handling missing companies from CSV file."""
import csv
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from api.batch_xbrl_finder import create_browser_and_context, fetch_xbrl_for_company
from playwright.async_api import async_playwright


def _missing_tracker_csv_path() -> Path:
    """Get path to missing_companies.csv"""
    src_dir = Path(__file__).resolve().parents[2]   # points to src/
    data_dir = src_dir / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "missing_companies.csv"


class MissingCompanyService:
    """Service for managing missing companies."""
    
    @staticmethod
    def get_missing_companies() -> List[Dict[str, Any]]:
        """
        Read missing companies from CSV file.
        Returns list of company records with timestamp, company_name, symbol, scrip_code, etc.
        """
        csv_path = _missing_tracker_csv_path()
        print(f"[DEBUG] Looking for missing companies at: {csv_path}")
        
        if not csv_path.exists():
            print(f"[DEBUG] CSV file does not exist: {csv_path}")
            return []
        
        missing_companies = []
        try:
            with open(csv_path, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    print(f"[DEBUG] CSV fieldnames: {reader.fieldnames}")
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
                            print(f"[DEBUG] Added missing company: {company_data['company_name']}")
        except Exception as e:
            print(f"[ERROR] Error reading missing companies CSV: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"[DEBUG] Total missing companies loaded: {len(missing_companies)}")
        return missing_companies
    
    @staticmethod
    def remove_missing_company(scrip_code: str) -> bool:
        """
        Remove a company from missing_companies.csv after processing.
        Rewrites the CSV without the specified scrip_code.
        """
        csv_path = _missing_tracker_csv_path()
        
        if not csv_path.exists():
            return False
        
        try:
            # Read all records
            records = []
            with open(csv_path, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                for row in reader:
                    if row.get('scrip_code', '').strip() != scrip_code.strip():
                        records.append(row)
            
            # Rewrite without the removed record
            if fieldnames:
                with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(records)
            
            return True
        except Exception as e:
            print(f"Error removing missing company from CSV: {e}")
            return False
    
    @staticmethod
    async def process_missing_company(
        scrip_code: str,
        company_name: str,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a missing company: fetch XBRL URLs using the existing browser-based mechanism.
        Uses fetch_xbrl_for_company from batch_xbrl_finder which handles all edge cases.
        
        Returns:
        {
            'scrip_code': str,
            'company_name': str,
            'xbrl_url': Optional[str],
            'period': Optional[str],
            'error': Optional[str],
            'attempts': int,
            'duration_ms': int
        }
        """
        try:
            # Use scrip_code if available, otherwise use company_name
            query = scrip_code.strip() if scrip_code and scrip_code.strip() else company_name
            
            # Use the browser-based mechanism from batch_xbrl_finder
            async with async_playwright() as p:
                browser, ctx = await create_browser_and_context(p)
                try:
                    url, period, attempts, annual_url, annual_period, quarterly_url, quarterly_period = await fetch_xbrl_for_company(
                        ctx, 
                        company=query, 
                        prefer="any"
                    )
                    
                    return {
                        'scrip_code': scrip_code or '',
                        'company_name': company_name,
                        'xbrl_url': url,
                        'period': period,
                        'error': None if url else "No XBRL link found after exhaustive attempts",
                        'attempts': attempts,
                        'duration_ms': 0,
                    }
                finally:
                    await ctx.close()
                    
        except Exception as e:
            return {
                'scrip_code': scrip_code or '',
                'company_name': company_name,
                'xbrl_url': None,
                'period': None,
                'error': str(e),
                'attempts': 0,
                'duration_ms': 0,
            }
    
    @staticmethod
    async def process_missing_companies_batch(
        scrip_codes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Process multiple missing companies.
        If scrip_codes is None, process all missing companies.
        
        Returns progress and results for each company.
        """
        missing_companies = MissingCompanyService.get_missing_companies()
        
        # Filter by scrip_codes if provided
        if scrip_codes:
            scrip_codes_set = {s.strip().lower() for s in scrip_codes}
            missing_companies = [
                c for c in missing_companies
                if c['scrip_code'].strip().lower() in scrip_codes_set
            ]
        
        results = []
        total = len(missing_companies)
        
        for idx, company in enumerate(missing_companies, start=1):
            try:
                result = await MissingCompanyService.process_missing_company(
                    scrip_code=company['scrip_code'],
                    company_name=company['company_name'],
                    symbol=company['symbol'],
                )
                results.append(result)
                
                # Remove from CSV if successfully found XBRL
                if result.get('xbrl_url'):
                    MissingCompanyService.remove_missing_company(company['scrip_code'])
                    
            except Exception as e:
                results.append({
                    'scrip_code': company['scrip_code'],
                    'company_name': company['company_name'],
                    'xbrl_url': None,
                    'period': None,
                    'error': f"Batch processing error: {str(e)}",
                    'attempts': 0,
                    'duration_ms': 0,
                })
            
            # Small delay between requests to avoid overwhelming the BSE
            if idx < total:
                await asyncio.sleep(0.5)
        
        return {
            'total': total,
            'processed': len(results),
            'timestamp': datetime.now().isoformat(),
            'results': results,
        }
