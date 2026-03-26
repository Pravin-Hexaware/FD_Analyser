import asyncio
import csv
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from repository.sqlite_repository import SqliteRepository
from api.batch_xbrl_finder import (
    create_browser_and_context,
    fetch_xbrl_for_company,
)
from api.xbrl_route import calculate_metrics, extract_annual
from api.Xbrl_annual_extractor import calculate_metrics_fourd
from service.html_extraction_service import extract_html_data
from service.xml_extraction_service import extract_xbrl_data

router = APIRouter()


@router.websocket("/ws/xbrl-fetch-latest")
async def websocket_xbrl_fetch(websocket: WebSocket) -> None:
    """WebSocket endpoint that reads companies from CSV, fetches XBRL URLs, and stores them in SQLite."""
    await websocket.accept()

    csv_path = Path(__file__).resolve().parents[1] / "Data" / "input_companies.csv"
    if not csv_path.exists():
        await websocket.send_json({"error": f"CSV file not found: {csv_path}"})
        await websocket.close()
        return

    repo = SqliteRepository()

    try:
        await websocket.send_json({"status": "starting", "csv_path": str(csv_path)})

        # Read CSV once
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records = [r for r in reader if r.get("Scrip-code")]

        await websocket.send_json(
            {"status": "read_csv", "records": len(records)}
        )

        # Determine restart/resume point based on recent (<=10 days) xbrl filing entries.
        start_idx = 1
        now = datetime.utcnow()
        for idx, row in enumerate(records, start=1):
            scrip_code = (row.get("Scrip-code") or "").strip()
            if not scrip_code:
                continue
            try:
                if repo.xbrl_filing_recent(scrip_code, days=10):
                    continue
                start_idx = idx
                break
            except Exception as e:
                await websocket.send_json({
                    "status": "resume_check_failed",
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })
                start_idx = idx
                break

        if start_idx > len(records):
            await websocket.send_json({"status": "already_up_to_date", "start_idx": start_idx})
            await websocket.send_json({"status": "complete"})
            return

        await websocket.send_json({"status": "resume_from", "start_idx": start_idx})

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser, ctx = await create_browser_and_context(p)
            try:
                for idx, row in enumerate(records, start=1):
                        if idx < start_idx:
                            continue

                        scrip_code = (row.get("Scrip-code") or "").strip()
                        symbol = (row.get("Symbol") or "").strip()
                        name = (row.get("Company") or "").strip()
                        sector = (row.get("Sector ") or "").strip()
                        industry = (row.get("Industry") or "").strip()

                        if not scrip_code:
                            await websocket.send_json({"idx": idx, "status": "skipped", "reason": "empty scrip_code"})
                            continue

                        try:
                            async with asyncio.timeout(180):
                                # Ensure company exists; if already present, keep it as-is
                                if not repo.company_exists(scrip_code):
                                    repo.upsert_company(
                                    company_name=name,
                                    symbol=symbol,
                                    scrip_code=scrip_code,
                                    sector=sector,
                                    industry=industry,
                                )

                            # Fetch both quarterly and annual report URLs in one pass (faster)
                            q_url = None
                            q_period = None
                            a_url = None
                            a_period = None
                            attempts = 0
                            try:
                                _, _, attempts, a_url, a_period, q_url, q_period = await fetch_xbrl_for_company(ctx, scrip_code, prefer="any")
                            except Exception as e:
                                await websocket.send_json({
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "symbol": symbol,
                                    "report_type": "mixed",
                                    "error": str(e),
                                    "traceback": traceback.format_exc(),
                                })

                            # Store and emit quarterly
                            q_id = None
                            q_stored = False
                            if q_url:
                                if repo.xbrl_filing_exists(scrip_code, q_url, report_type="quarterly"):
                                    q_stored = True
                                    q_id = repo.get_xbrl_filing_id(scrip_code, q_url, report_type="quarterly")
                                else:
                                    q_id = repo.insert_xbrl_filing(
                                        scrip_code=scrip_code,
                                        symbol=symbol,
                                        xbrl_link=q_url,
                                        publication_date=q_period,
                                        report_type="quarterly",
                                    )
                                    q_stored = True

                                await websocket.send_json({
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "symbol": symbol,
                                    "report_type": "quarterly",
                                    "period": q_period,
                                    "url": q_url,
                                    "id": q_id,
                                    "stored": q_stored,
                                    "attempts": attempts,
                                })

                            # Store and emit annual
                            a_id = None
                            a_stored = False
                            if a_url:
                                if repo.xbrl_filing_exists(scrip_code, a_url, report_type="annual"):
                                    a_stored = True
                                    a_id = repo.get_xbrl_filing_id(scrip_code, a_url, report_type="annual")
                                else:
                                    a_id = repo.insert_xbrl_filing(
                                        scrip_code=scrip_code,
                                        symbol=symbol,
                                        xbrl_link=a_url,
                                        publication_date=a_period,
                                        report_type="annual",
                                    )
                                    a_stored = True

                                await websocket.send_json({
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "symbol": symbol,
                                    "report_type": "annual",
                                    "period": a_period,
                                    "url": a_url,
                                    "id": a_id,
                                    "stored": a_stored,
                                    "attempts": attempts,
                                })

                        except asyncio.TimeoutError as te:
                            await websocket.send_json({
                                "idx": idx,
                                "scrip_code": scrip_code,
                                "status": "timeout",
                                "error": "Per-entry timeout exceeded (180s)",
                                "detail": str(te),
                                "traceback": traceback.format_exc(),
                            })
                            continue
                        except Exception as row_error:
                            await websocket.send_json({
                                "idx": idx,
                                "scrip_code": scrip_code,
                                "status": "row_error",
                                "error": str(row_error),
                                "traceback": traceback.format_exc(),
                            })
                            continue

            finally:
                try:
                    await browser.close()
                except Exception:
                    pass

        await websocket.send_json({"status": "complete"})

    except WebSocketDisconnect:
        # Client disconnected
        pass
    except Exception as e:
        await websocket.send_json({"error": str(e), "traceback": traceback.format_exc()})
        await websocket.close()
    finally:
        try:
            repo.close()
        except Exception:
            pass


@router.websocket("/ws/xbrl-extract-from-db")
async def websocket_extract_from_db(websocket: WebSocket) -> None:
    """WebSocket endpoint: read XBRL URLs from DB, extract metrics, and store them in a second table."""
    await websocket.accept()

    repo = SqliteRepository()

    try:
        await websocket.send_json({"status": "starting"})

        filings = repo.get_xbrl_filings()
        await websocket.send_json({"status": "found_filings", "count": len(filings)})

        for idx, f in enumerate(filings, start=1):
            scrip_code = f.get("scrip_code")
            xbrl_link = f.get("xbrl_link")

            if not scrip_code or not xbrl_link:
                await websocket.send_json({
                    "idx": idx,
                    "status": "invalid_filing",
                    "reason": "missing scrip_code or xbrl_link",
                    "filing": f,
                })
                continue

            raw_report_type = str(f.get("report_type", "quarterly") or "quarterly").strip().lower()
            report_type = "annual" if raw_report_type in ("annual", "yearly") else "quarterly"

            await websocket.send_json({
                "idx": idx,
                "scrip_code": scrip_code,
                "xbrl_link": xbrl_link,
                "status": "processing",
                "report_type": report_type,
            })

            if repo.xbrl_extraction_exists(scrip_code, xbrl_link, report_type):
                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "xbrl_link": xbrl_link,
                    "status": "skipped_already_extracted",
                })
                continue

            try:
                if xbrl_link.lower().endswith(".xml"):
                    extracted = extract_xbrl_data(xbrl_link, only_prefix=None)
                    data_type = "xml"
                else:
                    extracted = extract_html_data(xbrl_link)
                    data_type = "html"

                # report_type already normalized above (annual/yearly -> annual, else quarterly)
                if report_type == "annual":
                    # For annual reports, use the dedicated extract_annual function
                    from api.xbrl_route import ExtractAnnualRequest
                    annual_request = ExtractAnnualRequest(url=xbrl_link)
                    response_data = await extract_annual(annual_request)
                    
                    # Extract data from response
                    if response_data.get("error"):
                        await websocket.send_json({
                            "idx": idx,
                            "scrip_code": scrip_code,
                            "xbrl_link": xbrl_link,
                            "status": "extraction_error",
                            "error": response_data.get("error"),
                        })
                        continue

                    # Store annual metrics in database
                    period = repo.get_period_by_xbrl_link(xbrl_link)
                    repo.insert_annual_extraction(
                        scrip_code=scrip_code,
                        xbrl_link=xbrl_link,
                        period=period,
                        company_name=response_data.get("company_name"),
                        company_symbol=response_data.get("company_symbol"),
                        currency=response_data.get("currency"),
                        level_of_rounding=response_data.get("level_of_rounding"),
                        reporting_type=response_data.get("reporting_type"),
                        nature_of_report=response_data.get("NatureOfReport"),

                        # Quarterly_Earnings prefixed
                        # quarterly_sales=response_data["Quarterly_Earnings"].get("Sales"),
                        # quarterly_expenses=response_data["Quarterly_Earnings"].get("Expenses"),
                        # quarterly_operating_profit=response_data["Quarterly_Earnings"].get("OperatingProfit"),
                        # quarterly_opm_percentage=response_data["Quarterly_Earnings"].get("OPM_percentage"),
                        # quarterly_other_income=response_data["Quarterly_Earnings"].get("OtherIncome"),
                        # quarterly_cost_of_materials_consumed=response_data["Quarterly_Earnings"].get("CostOfMaterialsConsumed"),
                        # quarterly_employee_benefit_expense=response_data["Quarterly_Earnings"].get("EmployeeBenefitExpense"),
                        # quarterly_other_expenses=response_data["Quarterly_Earnings"].get("OtherExpenses"),
                        # quarterly_interest=response_data["Quarterly_Earnings"].get("Interest"),
                        # quarterly_depreciation=response_data["Quarterly_Earnings"].get("Depreciation"),
                        # quarterly_profit_before_tax=response_data["Quarterly_Earnings"].get("ProfitBeforeTax"),
                        # quarterly_current_tax=response_data["Quarterly_Earnings"].get("CurrentTax"),
                        # quarterly_deferred_tax=response_data["Quarterly_Earnings"].get("DeferredTax"),
                        # quarterly_tax=response_data["Quarterly_Earnings"].get("Tax"),
                        # quarterly_tax_percent=response_data["Quarterly_Earnings"].get("Tax_percent"),
                        # quarterly_net_profit=response_data["Quarterly_Earnings"].get("NetProfit"),
                        # quarterly_eps_in_rs=response_data["Quarterly_Earnings"].get("EPS_in_RS"),

                        # Profit and Loss (annual)
                        sales=response_data["Profit and Loss"].get("Sales"),
                        expenses=response_data["Profit and Loss"].get("Expenses"),
                        operating_profit=response_data["Profit and Loss"].get("OperatingProfit"),
                        opm_percentage=response_data["Profit and Loss"].get("OPM_percentage"),
                        other_income=response_data["Profit and Loss"].get("OtherIncome"),
                        interest=response_data["Profit and Loss"].get("Interest"),
                        depreciation=response_data["Profit and Loss"].get("Depreciation"),
                        profit_before_tax=response_data["Profit and Loss"].get("ProfitBeforeTax"),
                        tax_percent=response_data["Profit and Loss"].get("Tax_percent"),
                        net_profit=response_data["Profit and Loss"].get("NetProfit"),
                        eps_in_rs=response_data["Profit and Loss"].get("EPS_in_RS"),

                        # Balance sheet
                        equity_capital=response_data["Balance sheet"].get("EquityCapital"),
                        reserves=response_data["Balance sheet"].get("Reserves"),
                        trade_payables_current=response_data["Balance sheet"].get("TradePayablesCurrent"),
                        borrowings=response_data["Balance sheet"].get("Borrowings"),
                        other_liabilities=response_data["Balance sheet"].get("OtherLiabilities"),
                        total_liabilities=response_data["Balance sheet"].get("TotalLiabilities"),
                        total_equity=response_data["Balance sheet"].get("TotalEquity"),
                        fixed_assets=response_data["Balance sheet"].get("FixedAssets"),
                        cwip=response_data["Balance sheet"].get("CWIP"),
                        investments=response_data["Balance sheet"].get("Investments"),
                        total_assets=response_data["Balance sheet"].get("TotalAssets"),

                        # Cashflow
                        cash_from_operating_activity=response_data["Cashflow"].get("CashFromOperatingActivity"),
                        cash_from_investing_activity=response_data["Cashflow"].get("CashFromInvestingActivity"),
                        cash_from_financing_activity=response_data["Cashflow"].get("CashFromFinancingActivity"),
                    )
                    await asyncio.sleep(0.001)
                else:  # quarterly
                    metrics = calculate_metrics(extracted)
                    response_data = [
                        {
                            "url": xbrl_link,
                            "type": data_type,
                            "company_name": metrics.get("company_name"),
                            "company_symbol": metrics.get("company_symbol"),
                            "currency": metrics.get("currency"),
                            "level_of_rounding": metrics.get("level_of_rounding"),
                            "reporting_type": metrics.get("reporting_type"),
                            "NatureOfReport": metrics.get("NatureOfReport"),
                            "Sales": metrics.get("Sales"),
                            "Expenses": metrics.get("Expenses"),
                            "OperatingProfit": metrics.get("OperatingProfit"),
                            "OPM_percentage": metrics.get("OPM_percentage"),
                            "OtherIncome": metrics.get("OtherIncome"),
                            "CostOfMaterialsConsumed": metrics.get("CostOfMaterialsConsumed"),
                            "EmployeeBenefitExpense": metrics.get("EmployeeBenefitExpense"),
                            "OtherExpenses": metrics.get("OtherExpenses"),
                            "Interest": metrics.get("Interest"),
                            "Depreciation": metrics.get("Depreciation"),
                            "ProfitBeforeTax": metrics.get("ProfitBeforeTax"),
                            "CurrentTax": metrics.get("CurrentTax"),
                            "DeferredTax": metrics.get("DeferredTax"),
                            "Tax": metrics.get("Tax"),
                            "Tax_percent": metrics.get("Tax_percent"),
                            "NetProfit": metrics.get("NetProfit"),
                            "EPS_in_RS": metrics.get("EPS_in_RS"),
                            "error": None
                        }
                    ]
                    # Store quarterly metrics
                    period = repo.get_period_by_xbrl_link(xbrl_link)
                    repo.insert_quarterly_extraction(
                        scrip_code=scrip_code,
                        xbrl_link=xbrl_link,
                        period=period,
                        company_name=metrics.get("company_name"),
                        company_symbol=metrics.get("company_symbol"),
                        currency=metrics.get("currency"),
                        level_of_rounding=metrics.get("level_of_rounding"),
                        reporting_type=metrics.get("reporting_type"),
                        nature_of_report=metrics.get("NatureOfReport"),
                        sales=metrics.get("Sales"),
                        expenses=metrics.get("Expenses"),
                        operating_profit=metrics.get("OperatingProfit"),
                        opm_percentage=metrics.get("OPM_percentage"),
                        other_income=metrics.get("OtherIncome"),
                        cost_of_materials_consumed=metrics.get("CostOfMaterialsConsumed"),
                        employee_benefit_expense=metrics.get("EmployeeBenefitExpense"),
                        other_expenses=metrics.get("OtherExpenses"),
                        interest=metrics.get("Interest"),
                        depreciation=metrics.get("Depreciation"),
                        profit_before_tax=metrics.get("ProfitBeforeTax"),
                        current_tax=metrics.get("CurrentTax"),
                        deferred_tax=metrics.get("DeferredTax"),
                        tax=metrics.get("Tax"),
                        tax_percent=metrics.get("Tax_percent"),
                        net_profit=metrics.get("NetProfit"),
                        eps_in_rs=metrics.get("EPS_in_RS"),
                    )
                    await websocket.send_json({
                        "idx": idx,
                        "scrip_code": scrip_code,
                        "xbrl_link": xbrl_link,
                        "status": "stored",
                        "report_type": report_type,
                    })
                    await asyncio.sleep(0.001)

                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "xbrl_link": xbrl_link,
                    "status": "extracted",
                    "data": response_data,
                })

            except Exception as e:
                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "xbrl_link": xbrl_link,
                    "error": str(e),
                })

        await websocket.send_json({"status": "complete"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"error": str(e)})
        await websocket.close()
    finally:
        try:
            repo.close()
        except Exception:
            pass
