"""Service for handling missing companies from CSV file."""
import csv
import asyncio
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from api.batch_xbrl_finder import create_browser_and_context, get_all_std_xbrl_urls, fetch_xbrl_content
from playwright.async_api import async_playwright
from repository.sqlite_repository import SqliteRepository
from service.html_parser_service import html_dom_to_structured_json_from_content
from service.xml_extraction_service import extract_xbrl_data_from_bytes


def _missing_tracker_csv_path() -> Path:
    """Get path to missing_companies.csv"""
    src_dir = Path(__file__).resolve().parents[2]   # points to src/
    data_dir = src_dir / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "missing_companies.csv"


def _missing_company_log_dir() -> Path:
    """Get path to the missing company processing logs directory."""
    src_dir = Path(__file__).resolve().parents[2]
    logs_dir = src_dir / "logs" / "missing_company"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _new_missing_company_log_file(scrip_code: str) -> Path:
    """Create a new log file path for a missing company processing run."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_code = re.sub(r"[^a-zA-Z0-9_-]", "_", scrip_code or "unknown")
    return _missing_company_log_dir() / f"missing_company_{safe_code}_{timestamp}.log"


def _append_missing_company_log(log_file: Path, payload: Dict[str, Any]) -> None:
    try:
        with open(log_file, mode='a', encoding='utf-8') as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[WARN] Unable to write missing company log: {e}")


def _write_parsed_json_file(scrip_code: str, company_name: str, period: str, parsed_json: Any) -> Path:
    logs_dir = _missing_company_log_dir()
    safe_period = re.sub(r"[^a-zA-Z0-9_-]", "_", period or "unknown")
    safe_code = re.sub(r"[^a-zA-Z0-9_-]", "_", scrip_code or "unknown")
    filename = f"parsed_{safe_code}_{safe_period}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path = logs_dir / filename
    try:
        with open(path, mode='w', encoding='utf-8') as fh:
            json.dump(parsed_json, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Unable to write parsed JSON file: {e}")
    return path


class MissingCompanyService:
    """Service for managing missing companies."""

    _processing_lock: asyncio.Lock = asyncio.Lock()
    
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
    def _is_html_content(raw_text: str) -> bool:
        lower = (raw_text or "").lower()
        return (
            '<html' in lower
            or '<body' in lower
            or '<!doctype html' in lower
            or '<ix:' in lower
        )

    @staticmethod
    def _determine_extraction_type(publication_date: Optional[str]) -> str:
        if not publication_date:
            return 'quarterly'
        value = publication_date.strip().lower()
        if any(token in value for token in ['q1', 'q2', 'q3', 'q4', 'quarter', 'qtr', 'q']):
            return 'quarterly'
        return 'annual'

    @staticmethod
    async def _fetch_and_store_xbrl_for_company(
        ctx,
        repo: SqliteRepository,
        scrip_code: str,
        company_name: str,
        symbol: Optional[str],
        xbrl_url: str,
        publication_date: Optional[str],
        log_file: Optional[Path] = None,
        report_type: str = 'std',
        raw_content: Optional[Any] = None,
        industry: Optional[str] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            'scrip_code': scrip_code,
            'company_name': company_name,
            'symbol': symbol or '',
            'xbrl_url': xbrl_url,
            'publication_date': publication_date,
            'report_type': report_type,
            'stored_filing': False,
            'extracted': False,
            'error': None,
        }

        if not xbrl_url:
            result['error'] = 'No XBRL URL provided.'
            return result

        if raw_content is None:
            raw_content = await fetch_xbrl_content(ctx, xbrl_url)
        if not raw_content:
            result['error'] = f'Unable to fetch raw XBRL content from {xbrl_url}'
            return result

        raw_text = raw_content if isinstance(raw_content, str) else raw_content
        raw_bytes = raw_text.encode('utf-8') if isinstance(raw_text, str) else raw_text

        if log_file is not None:
            _append_missing_company_log(log_file, {
                'stage': 'found_url',
                'scrip_code': scrip_code,
                'company_name': company_name,
                'xbrl_url': xbrl_url,
                'period': publication_date,
                'message': 'URL discovered and content fetch starting',
            })

        print(json.dumps({
            'scrip_code': scrip_code,
            'company_name': company_name,
            'url': xbrl_url,
            'period': publication_date,
            'industry': industry,
        }, ensure_ascii=False))

        normalized_company_name = company_name.strip().upper()
        normalized_symbol = symbol.strip().upper() if symbol else None

        # Ensure company exists in database for joining later
        repo.upsert_company(
            company_name=normalized_company_name,
            symbol=normalized_symbol,
            scrip_code=scrip_code,
            sector=industry.strip() if industry else None,
            industry=industry.strip() if industry else None,
        )

        if not repo.xbrl_filing_exists(scrip_code, xbrl_url, report_type=report_type):
            repo.insert_xbrl_filing(
                scrip_code=scrip_code,
                symbol=symbol,
                xbrl_link=xbrl_url,
                publication_date=publication_date,
                report_type=report_type,
                raw_content=raw_text,
            )
        result['stored_filing'] = True

        extraction_type = MissingCompanyService._determine_extraction_type(publication_date)

        try:
            parsed_json = (
                html_dom_to_structured_json_from_content(raw_bytes)
                if MissingCompanyService._is_html_content(raw_text)
                else extract_xbrl_data_from_bytes(raw_bytes, only_prefix='in-bse-fin')
            )
        except Exception as parse_error:
            result['error'] = f'Failed to parse XBRL content: {parse_error}'
            if log_file is not None:
                _append_missing_company_log(log_file, {
                    'stage': 'parse_error',
                    'scrip_code': scrip_code,
                    'company_name': company_name,
                    'xbrl_url': xbrl_url,
                    'period': publication_date,
                    'error': str(parse_error),
                })
            return result

        if parsed_json is None:
            result['error'] = 'Parsed XBRL content was empty.'
            if log_file is not None:
                _append_missing_company_log(log_file, {
                    'stage': 'empty_parse',
                    'scrip_code': scrip_code,
                    'company_name': company_name,
                    'xbrl_url': xbrl_url,
                    'period': publication_date,
                })
            return result

        if repo.xbrl_extraction_exists(scrip_code, xbrl_url, extraction_type):
            result['extracted'] = True
            if log_file is not None:
                _append_missing_company_log(log_file, {
                    'stage': 'already_extracted',
                    'scrip_code': scrip_code,
                    'company_name': company_name,
                    'xbrl_url': xbrl_url,
                    'period': publication_date,
                    'extraction_type': extraction_type,
                })
            return result

        parsed_json_str = json.dumps(parsed_json, ensure_ascii=False, separators=(',', ':'))
        parsed_output_file = None
        if log_file is not None:
            parsed_output_file = _write_parsed_json_file(scrip_code, company_name, publication_date or 'unknown', parsed_json)
            _append_missing_company_log(log_file, {
                'stage': 'parsed_json_saved',
                'scrip_code': scrip_code,
                'company_name': company_name,
                'xbrl_url': xbrl_url,
                'period': publication_date,
                'parsed_json_path': str(parsed_output_file),
            })
        if extraction_type == 'quarterly':
            caps_company_name = company_name.strip().upper()
            repo.insert_quarterly_extraction(
                scrip_code=scrip_code,
                company_name=caps_company_name,
                xbrl_link=xbrl_url,
                publication_date=publication_date or '',
                report_type=report_type,
                parsed_json=parsed_json_str,
            )
        else:
            if not publication_date or len(publication_date) < 2 or publication_date[1].upper() != 'C':
                result['error'] = (
                    f"Skipped annual extraction because period does not meet required format: {publication_date}"
                )
                if log_file is not None:
                    _append_missing_company_log(log_file, {
                        'stage': 'skipped_annual_extraction',
                        'scrip_code': scrip_code,
                        'company_name': company_name,
                        'xbrl_url': xbrl_url,
                        'period': publication_date,
                        'reason': 'period[1] != C',
                    })
                return result

            cap_company_name = company_name.strip().upper()
            #cap_symbol = symbol.strip().upper() if symbol else None
            repo.insert_annual_extraction(
                scrip_code=scrip_code,
                company_name=cap_company_name,
                xbrl_link=xbrl_url,
                publication_date=publication_date or '',
                report_type=report_type,
                parsed_json=parsed_json_str,
            )
        result['extracted'] = True
        return result

    @staticmethod
    async def process_missing_company_full(
        scrip_code: str,
        company_name: str,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = scrip_code.strip() if scrip_code and scrip_code.strip() else company_name
        repo = SqliteRepository()
        browser = None
        log_file = _new_missing_company_log_file(scrip_code or company_name)
        _append_missing_company_log(log_file, {
            'stage': 'started',
            'scrip_code': scrip_code,
            'company_name': company_name,
            'symbol': symbol,
            'query': query,
            'timestamp': datetime.now().isoformat(),
        })
        try:
            async with async_playwright() as p:
                browser, ctx = await create_browser_and_context(p)
                attempts = 0
                results = []
                async for xbrl_url, xbrl_period, xbrl_type, raw_content, industry in get_all_std_xbrl_urls(ctx, query):
                    if not xbrl_url or xbrl_type != 'std':
                        continue

                    attempts += 1
                    results.append(await MissingCompanyService._fetch_and_store_xbrl_for_company(
                        ctx,
                        repo,
                        scrip_code,
                        company_name,
                        symbol,
                        xbrl_url,
                        xbrl_period,
                        log_file=log_file,
                        report_type='std',
                        raw_content=raw_content,
                        industry=industry,
                    ))

                if not results:
                    _append_missing_company_log(log_file, {
                        'stage': 'no_urls_found',
                        'scrip_code': scrip_code,
                        'company_name': company_name,
                        'symbol': symbol,
                        'query': query,
                        'attempts': attempts,
                    })

                success = any(r.get('stored_filing') or r.get('extracted') for r in results)
                summary = {
                    'scrip_code': scrip_code or '',
                    'company_name': company_name,
                    'symbol': symbol or '',
                    'attempts': attempts,
                    'results': results,
                    'success': success,
                    'error': None if success else 'No XBRL URLs or extraction failed.',
                }
                if log_file is not None:
                    _append_missing_company_log(log_file, {
                        'stage': 'completed',
                        'scrip_code': scrip_code,
                        'company_name': company_name,
                        'symbol': symbol,
                        'attempts': attempts,
                        'success': success,
                        'results': results,
                        'error': summary['error'],
                    })
                return summary
        except Exception as e:
            return {
                'scrip_code': scrip_code or '',
                'company_name': company_name,
                'symbol': symbol or '',
                'attempts': 0,
                'results': [],
                'success': False,
                'error': str(e),
            }
        finally:
            try:
                if 'ctx' in locals() and ctx is not None:
                    await ctx.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    await browser.close()
            except Exception:
                pass
            try:
                repo.close()
            except Exception:
                pass

    @staticmethod
    async def process_missing_companies_batch(
        scrip_codes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Process multiple missing companies.
        If scrip_codes is None, process all missing companies.
        
        Returns progress and results for each company.
        """
        async with MissingCompanyService._processing_lock:
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
                    result = await MissingCompanyService.process_missing_company_full(
                        scrip_code=company['scrip_code'],
                        company_name=company['company_name'],
                        symbol=company['symbol'],
                    )
                    results.append(result)
                    
                    if result.get('success'):
                        MissingCompanyService.remove_missing_company(company['scrip_code'])
                except Exception as e:
                    results.append({
                        'scrip_code': company['scrip_code'],
                        'company_name': company['company_name'],
                        'symbol': company['symbol'],
                        'attempts': 0,
                        'results': [],
                        'success': False,
                        'error': f'Batch processing error: {str(e)}',
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
