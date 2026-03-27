from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from repository.sqlite_repository import SqliteRepository

router = APIRouter()


@router.get("/{scrip_code}/financials")
async def get_company_financials(
    scrip_code: str,
    frequency: str = "annual"  # "annual" or "quarterly"
):
    """Get financial data for a company."""
    try:
        repo = SqliteRepository()
        
        # Get company info
        cur = repo._conn.cursor()
        cur.execute(
            """
            SELECT id, company_name, symbol, sector, industry
            FROM company_table
            WHERE scrip_code = ?
            """,
            (scrip_code,)
        )
        
        company_row = cur.fetchone()
        if not company_row:
            raise HTTPException(status_code=404, detail="Company not found")
        
        company_id, company_name, symbol, sector, industry = company_row
        
        # Get financial data based on frequency
        if frequency.lower() == "quarterly":
            cur.execute(
                """
                SELECT *
                FROM quarterly_table
                WHERE scrip_code = ?
                ORDER BY created_at DESC
                LIMIT 20
                """,
                (scrip_code,)
            )
        else:
            cur.execute(
                """
                SELECT *
                FROM annual_table
                WHERE scrip_code = ?
                ORDER BY created_at DESC
                LIMIT 20
                """,
                (scrip_code,)
            )
        
        rows = cur.fetchall()
        repo.close()
        
        # Format the data - convert Row objects to dictionaries with all columns
        financials = []
        for row in rows:
            # Convert sqlite3.Row to dict (this includes all columns from the query)
            financial_dict = dict(row)
            financials.append(financial_dict)
        
        return {
            "company_id": company_id,
            "company_name": company_name,
            "symbol": symbol,
            "sector": sector,
            "industry": industry,
            "scrip_code": scrip_code,
            "frequency": frequency,
            "financials": financials
        }
    except HTTPException:
        raise
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/companies/compare", response_model=Dict[str, Any])
async def compare_companies(request: Dict[str, Any]):
    """Compare multiple companies with their latest financials."""
    try:
        scrip_codes = request.get("scrip_codes", [])
        frequency = request.get("frequency", "annual")
        
        if not scrip_codes or len(scrip_codes) < 2:
            raise HTTPException(status_code=400, detail="At least 2 companies required for comparison")
        
        repo = SqliteRepository()
        companies_data = []
        
        for scrip_code in scrip_codes:
            cur = repo._conn.cursor()
            
            # Get company info
            cur.execute(
                """
                SELECT company_name, symbol, sector, industry
                FROM company_table
                WHERE scrip_code = ?
                """,
                (scrip_code,)
            )
            
            company_info = cur.fetchone()
            if not company_info:
                continue
            
            # Get latest financial data
            if frequency.lower() == "quarterly":
                cur.execute(
                    """
                    SELECT 
                        sales, expenses, operating_profit, opm_percentage,
                        net_profit, eps_in_rs, created_at
                    FROM quarterly_table
                    WHERE scrip_code = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (scrip_code,)
                )
            else:
                cur.execute(
                    """
                    SELECT 
                        sales, expenses, operating_profit, opm_percentage,
                        net_profit, eps_in_rs, equity_capital, total_assets,
                        borrowings, cash_from_operating_activity, created_at
                    FROM annual_table
                    WHERE scrip_code = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (scrip_code,)
                )
            
            fin_data = cur.fetchone()
            if fin_data:
                if frequency.lower() == "quarterly":
                    # Quarterly: only P&L data
                    # fin_data indices: sales(0), expenses(1), operating_profit(2), opm(3),
                    #                  net_profit(4), eps(5), created_at(6)
                    company_data = {
                        "scrip_code": scrip_code,
                        "company_name": company_info[0],
                        "symbol": company_info[1],
                        "sector": company_info[2],
                        "industry": company_info[3],
                        "sales": fin_data[0],
                        "expenses": fin_data[1],
                        "operating_profit": fin_data[2],
                        "opm": fin_data[3],
                        "pat": fin_data[4],
                        "eps": fin_data[5],
                        "equity": None,
                        "total_assets": None,
                        "borrowings": None,
                        "cfo": None,
                        "date": fin_data[6]
                    }
                else:
                    # Annual: has all data
                    company_data = {
                        "scrip_code": scrip_code,
                        "company_name": company_info[0],
                        "symbol": company_info[1],
                        "sector": company_info[2],
                        "industry": company_info[3],
                        "sales": fin_data[0],
                        "expenses": fin_data[1],
                        "operating_profit": fin_data[2],
                        "opm": fin_data[3],
                        "pat": fin_data[4],
                        "eps": fin_data[5],
                        "equity": fin_data[6],
                        "total_assets": fin_data[7],
                        "borrowings": fin_data[8],
                        "cfo": fin_data[9],
                        "date": fin_data[10]
                    }
                companies_data.append(company_data)
        
        repo.close()
        
        if not companies_data:
            raise HTTPException(status_code=404, detail="No financial data found for companies")
        
        return {
            "companies": companies_data,
            "frequency": frequency,
            "count": len(companies_data)
        }
    except HTTPException:
        raise
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))
