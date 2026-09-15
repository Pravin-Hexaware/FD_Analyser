"""Service for handling missing companies from CSV file."""
import csv
import asyncio
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from config.settings import LOGS_DIR, MISSING_COMPANIES_CSV
from services.batch_xbrl_finder import (
    BSE_URL,
    check_bse_landing_site_health,
    create_browser_and_context,
    fetch_xbrl_content,
    get_all_std_xbrl_urls,
)
from services.heal_service import BseWebsiteDown, PlaywrightHealBatchHalt, heal_results_portal
from automation.results_portal import WEBSITE_DOWN_DETAIL, is_site_down
from playwright.async_api import async_playwright
from repositories.sqlite_repository import SqliteRepository
from services.html_parser_service import html_dom_to_structured_json_from_content
from services.xml_extraction_service import extract_xbrl_data_from_bytes
from utils.fiscal_year import is_within_5year_range

PRODUCTION_PORTAL_PATH = Path(__file__).resolve().parents[1] / "automation" / "results_portal.py"

# Sentinel: caller did not prefetch raw content (legacy / direct calls).
_RAW_CONTENT_UNSET = object()


def _missing_tracker_csv_path() -> Path:
    """Canonical missing_companies.csv (same path chatbot + admin use)."""
    MISSING_COMPANIES_CSV.parent.mkdir(parents=True, exist_ok=True)
    return MISSING_COMPANIES_CSV


def _missing_company_log_dir() -> Path:
    """Get path to the missing company processing logs directory."""
    logs_dir = LOGS_DIR / "missing_company"
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
        raw_content: Optional[Any] = _RAW_CONTENT_UNSET,
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

        if raw_content is _RAW_CONTENT_UNSET:
            raw_content = await fetch_xbrl_content(ctx, xbrl_url)
        elif not raw_content:
            # Prefetched by collector but unprocessable (404/empty) — do not re-fetch.
            result['error'] = f'skipped_unprocessable: no raw content for {xbrl_url}'
            if log_file is not None:
                _append_missing_company_log(log_file, {
                    'stage': 'skipped_unprocessable',
                    'scrip_code': scrip_code,
                    'company_name': company_name,
                    'xbrl_url': xbrl_url,
                    'period': publication_date,
                    'reason': 'link present but raw content unavailable',
                })
            return result

        if not raw_content:
            result['error'] = f'Unable to fetch raw XBRL content from {xbrl_url}'
            if log_file is not None:
                _append_missing_company_log(log_file, {
                    'stage': 'skipped_unprocessable',
                    'scrip_code': scrip_code,
                    'company_name': company_name,
                    'xbrl_url': xbrl_url,
                    'period': publication_date,
                    'reason': 'unable to fetch raw content',
                })
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
                'message': 'URL discovered with raw content; storing',
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
        expected_scrip = scrip_code.strip() if scrip_code and scrip_code.strip() else None
        repo = SqliteRepository()
        browser = None
        ctx = None
        log_file = _new_missing_company_log_file(scrip_code or company_name)
        _append_missing_company_log(log_file, {
            'stage': 'started',
            'scrip_code': scrip_code,
            'company_name': company_name,
            'symbol': symbol,
            'query': query,
            'timestamp': datetime.now().isoformat(),
        })

        async def _collect_and_store(active_ctx) -> tuple:
            attempts = 0
            results = []
            consecutive_out_of_range = 0
            async for xbrl_url, xbrl_period, xbrl_type, raw_content, industry in get_all_std_xbrl_urls(
                active_ctx,
                query,
                expected_scrip=expected_scrip,
            ):
                if not xbrl_url or str(xbrl_type).lower() != 'std':
                    continue

                # Same past-5-FY gate + early exit as Fetch Filings WS
                if not is_within_5year_range(xbrl_period):
                    consecutive_out_of_range += 1
                    _append_missing_company_log(log_file, {
                        'stage': 'skipped_outside_5year_range',
                        'scrip_code': scrip_code,
                        'period': xbrl_period,
                        'url': xbrl_url,
                        'consecutive_out_of_range': consecutive_out_of_range,
                    })
                    if consecutive_out_of_range >= 2:
                        _append_missing_company_log(log_file, {
                            'stage': 'halting_collection',
                            'scrip_code': scrip_code,
                            'reason': (
                                '2 consecutive records outside 5-year range. '
                                'All remaining records assumed to be older.'
                            ),
                        })
                        break
                    continue

                consecutive_out_of_range = 0
                attempts += 1
                results.append(await MissingCompanyService._fetch_and_store_xbrl_for_company(
                    active_ctx,
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
            return attempts, results

        try:
            async with async_playwright() as p:
                browser, ctx = await create_browser_and_context(p)

                # Same downtime gate as Fetch Filings — empty landing grid ⇒ no heal.
                try:
                    health = await check_bse_landing_site_health(ctx)
                except Exception as health_exc:
                    _append_missing_company_log(log_file, {
                        'stage': 'site_health_probe_failed',
                        'error': str(health_exc),
                        'detail': 'proceed_to_collect',
                    })
                    health = None
                if health is not None and is_site_down(health):
                    _append_missing_company_log(log_file, {
                        'stage': 'website_down',
                        'detail': WEBSITE_DOWN_DETAIL,
                    })
                    return {
                        'scrip_code': scrip_code or '',
                        'company_name': company_name,
                        'symbol': symbol or '',
                        'attempts': 0,
                        'results': [],
                        'success': False,
                        'error': WEBSITE_DOWN_DETAIL,
                    }

                heal_attempted = False
                attempts = 0
                results: List[Dict[str, Any]] = []

                while True:
                    try:
                        attempts, results = await _collect_and_store(ctx)
                        break
                    except BseWebsiteDown as down_exc:
                        _append_missing_company_log(log_file, {
                            'stage': 'website_down',
                            'detail': str(down_exc),
                        })
                        return {
                            'scrip_code': scrip_code or '',
                            'company_name': company_name,
                            'symbol': symbol or '',
                            'attempts': attempts,
                            'results': results,
                            'success': False,
                            'error': str(down_exc) or WEBSITE_DOWN_DETAIL,
                        }
                    except PlaywrightHealBatchHalt as heal_halt:
                        needs_heal = getattr(heal_halt, 'needs_heal', False)
                        if not needs_heal or heal_attempted:
                            raise
                        heal_attempted = True
                        try:
                            pre_heal_health = await check_bse_landing_site_health(ctx)
                        except Exception as health_exc:
                            _append_missing_company_log(log_file, {
                                'stage': 'pre_heal_probe_failed',
                                'error': str(health_exc),
                                'detail': 'proceed_to_heal',
                            })
                            pre_heal_health = None
                        if pre_heal_health is not None and is_site_down(pre_heal_health):
                            return {
                                'scrip_code': scrip_code or '',
                                'company_name': company_name,
                                'symbol': symbol or '',
                                'attempts': attempts,
                                'results': results,
                                'success': False,
                                'error': WEBSITE_DOWN_DETAIL,
                            }

                        _append_missing_company_log(log_file, {
                            'stage': 'heal_started',
                            'reason': getattr(heal_halt, 'reason', str(heal_halt)),
                            'scrip_code': scrip_code,
                        })
                        try:
                            await asyncio.to_thread(
                                heal_results_portal,
                                BSE_URL,
                                PRODUCTION_PORTAL_PATH,
                                scrip_code or query,
                            )
                        except BseWebsiteDown as down_exc:
                            return {
                                'scrip_code': scrip_code or '',
                                'company_name': company_name,
                                'symbol': symbol or '',
                                'attempts': attempts,
                                'results': results,
                                'success': False,
                                'error': str(down_exc) or WEBSITE_DOWN_DETAIL,
                            }

                        # Recreate browser after portal promote (same as Fetch Filings WS).
                        try:
                            if ctx is not None:
                                await ctx.close()
                        except Exception:
                            pass
                        try:
                            if browser is not None:
                                await browser.close()
                        except Exception:
                            pass
                        browser, ctx = await create_browser_and_context(p)
                        _append_missing_company_log(log_file, {
                            'stage': 'heal_success_retrying',
                            'scrip_code': scrip_code,
                        })
                        continue

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
            _append_missing_company_log(log_file, {
                'stage': 'failed',
                'scrip_code': scrip_code,
                'error': str(e),
            })
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
                if ctx is not None:
                    await ctx.close()
            except Exception as e:
                print(f"Error closing context: {e}")
            try:
                if browser is not None:
                    await browser.close()
            except Exception as e:
                print(f"Error closing browser: {e}")
            try:
                repo.close()
            except Exception as e:
                print(f"Error closing repository: {e}")

    @staticmethod
    def _company_queue_key(company: Dict[str, Any]) -> str:
        key = (company.get('scrip_code') or '').strip().lower()
        if key:
            return key
        return f"name:{(company.get('company_name') or '').strip().lower()}"

    @staticmethod
    def _dedupe_fifo(companies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep first occurrence of each scrip/name (CSV top = sno 1)."""
        deduped: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for company in companies:
            key = MissingCompanyService._company_queue_key(company)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(company)
        return deduped

    @staticmethod
    async def process_missing_companies_batch(
        scrip_codes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Process missing companies as a FIFO CSV queue (sno 1 first).

        Re-reads the CSV after each company so mid-run appends are picked up
        at the end of the queue. Removes a row only after successful
        collect+extract. Failed companies are skipped for the rest of this
        run (left in CSV for a later worker).
        """
        async with MissingCompanyService._processing_lock:
            results: List[Dict[str, Any]] = []
            failed_keys: set[str] = set()
            scrip_codes_set = None
            if scrip_codes:
                scrip_codes_set = {s.strip().lower() for s in scrip_codes}

            while True:
                missing_companies = MissingCompanyService.get_missing_companies()
                if scrip_codes_set is not None:
                    missing_companies = [
                        c for c in missing_companies
                        if c['scrip_code'].strip().lower() in scrip_codes_set
                    ]

                queue = MissingCompanyService._dedupe_fifo(missing_companies)
                queue = [
                    c for c in queue
                    if MissingCompanyService._company_queue_key(c) not in failed_keys
                ]
                if not queue:
                    break

                company = queue[0]
                company_key = MissingCompanyService._company_queue_key(company)
                print(
                    f"[missing-queue] Processing head "
                    f"{company.get('company_name')} ({company.get('scrip_code')}) "
                    f"— {len(queue)} left in queue"
                )

                try:
                    result = await MissingCompanyService.process_missing_company_full(
                        scrip_code=company['scrip_code'],
                        company_name=company['company_name'],
                        symbol=company['symbol'],
                    )
                    results.append(result)

                    if result.get('success'):
                        MissingCompanyService.remove_missing_company(company['scrip_code'])
                        print(
                            f"[missing-queue] Removed {company.get('scrip_code')} "
                            f"after successful collect"
                        )
                    else:
                        failed_keys.add(company_key)
                        print(
                            f"[missing-queue] Leaving {company.get('scrip_code')} in CSV "
                            f"(failed this run); skipping for remainder of worker"
                        )
                except Exception as e:
                    failed_keys.add(company_key)
                    results.append({
                        'scrip_code': company['scrip_code'],
                        'company_name': company['company_name'],
                        'symbol': company['symbol'],
                        'attempts': 0,
                        'results': [],
                        'success': False,
                        'error': f'Batch processing error: {str(e)}',
                    })

                await asyncio.sleep(0.5)

        return {
            'total': len(results),
            'processed': len(results),
            'timestamp': datetime.now().isoformat(),
            'results': results,
        }
