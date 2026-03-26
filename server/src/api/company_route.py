from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from repository.sqlite_repository import SqliteRepository

router = APIRouter()


class CompanyInfo(BaseModel):
    id: str
    scrip_code: str
    company_name: str
    symbol: str
    sector: Optional[str]
    industry: Optional[str]


class CompanyFinancialData(BaseModel):
    scrip_code: str
    company_name: str
    symbol: str
    period: str
    frequency: str  # "annual" or "quarterly"
    
    # P&L data
    sales: Optional[float]
    operating_profit: Optional[float]
    opm_percentage: Optional[float]
    net_profit: Optional[float]
    eps_in_rs: Optional[float]
    
    # Balance sheet data
    equity_capital: Optional[float]
    total_assets: Optional[float]
    borrowings: Optional[float]
    
    # Cash flow data
    cash_from_operating_activity: Optional[float]
    
    # Ratios
    roce: Optional[float]


@router.get("/companies", response_model=List[CompanyInfo])
async def get_all_companies():
    """Get all companies from the database."""
    try:
        repo = SqliteRepository()
        cur = repo._conn.cursor()
        
        cur.execute(
            """
            SELECT id, scrip_code, company_name, symbol, sector, industry
            FROM company_table
            ORDER BY company_name
            """
        )
        
        rows = cur.fetchall()
        repo.close()
        
        companies = []
        for row in rows:
            # Handle both tuple and sqlite3.Row objects
            if hasattr(row, 'keys'):
                companies.append(CompanyInfo(
                    id=str(row['id']),
                    scrip_code=row['scrip_code'],
                    company_name=row['company_name'],
                    symbol=row['symbol'],
                    sector=row['sector'],
                    industry=row['industry']
                ))
            else:
                companies.append(CompanyInfo(
                    id=str(row[0]),
                    scrip_code=row[1],
                    company_name=row[2],
                    symbol=row[3],
                    sector=row[4],
                    industry=row[5]
                ))
        
        return companies
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{scrip_code}", response_model=CompanyInfo)
async def get_company_by_code(scrip_code: str):
    """Get a single company by scrip code."""
    try:
        repo = SqliteRepository()
        cur = repo._conn.cursor()
        
        cur.execute(
            """
            SELECT id, scrip_code, company_name, symbol, sector, industry
            FROM company_table
            WHERE scrip_code = ?
            """,
            (scrip_code,)
        )
        
        row = cur.fetchone()
        repo.close()
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Company with scrip_code '{scrip_code}' not found")
        
        # Handle both tuple and sqlite3.Row objects
        if hasattr(row, 'keys'):
            company = CompanyInfo(
                id=str(row['id']),
                scrip_code=row['scrip_code'],
                company_name=row['company_name'],
                symbol=row['symbol'],
                sector=row['sector'],
                industry=row['industry']
            )
        else:
            company = CompanyInfo(
                id=str(row[0]),
                scrip_code=row[1],
                company_name=row[2],
                symbol=row[3],
                sector=row[4],
                industry=row[5]
            )
        
        return company
    except HTTPException:
        raise
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{scrip_code}/financials")
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
