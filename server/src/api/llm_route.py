from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
from datetime import datetime
import uuid

from service.analysis_service import parse_query_and_get_companies, generate_answer_from_data
from repository.sqlite_repository import SqliteRepository

router = APIRouter()


class LLMQueryRequest(BaseModel):
    query: str


class ChatHistoryResponse(BaseModel):
    chat_id: str
    user_query: str
    response: str
    created_at: str
    title: str  # First 50 chars of query for display


def _determine_frequency(statement_frequency: str, statement_type: str, period: str) -> str:
    """Determine the frequency: annual or quarterly."""
    sf = (statement_frequency or "").strip().lower()
    st = (statement_type or "").strip().lower()
    p = (period or "").strip().lower()

    if sf in ["annual", "yearly", "year"]:
        return "annual"
    if sf in ["quarterly", "q", "3months", "3-month", "3 months"]:
        return "quarterly"

    annual_types = ["balance_sheet", "cash_flow", "profit_and_loss", "income_statement"]
    if any(t in st for t in annual_types):
        return "annual"

    if p in ["latest quarter", "latest q", "quarterly", "q1", "q2", "q3", "q4", "3months", "3-month", "3 months"]:
        return "quarterly"

    # Default to annual for strong annual indicator, else quarterly fallback
    if "annual" in st or "year" in st:
        return "annual"

    return "quarterly"  # safe default



def _should_include_peers(query: str) -> bool:
    """Return True only when query explicitly requests peers."""
    q = (query or "").strip().lower()
    if not q:
        return False
    if "peer" in q or "peers" in q:
        return True
    return False


def _fetch_company_data(repo: SqliteRepository, scrip_code: str, frequency: str, statement_type: str) -> Dict[str, Any]:
    """Fetch the latest data for a company and filter fields based on frequency and statement_type."""
    if frequency == "annual":
        data = repo.get_latest_annual_data(scrip_code)
    else:
        data = repo.get_latest_quarterly_data(scrip_code)
    
    if not data:
        return {}

    # Define field sets using DB column names
    quarterly_fields = [
        "sales", "expenses", "operating_profit", "opm_percentage", "other_income",
        "cost_of_materials_consumed", "employee_benefit_expense", "other_expenses",
        "interest", "depreciation", "profit_before_tax", "current_tax", "deferred_tax",
        "tax", "tax_percent", "net_profit", "eps_in_rs"
    ]
    
    annual_pl_fields = [
        "sales", "expenses", "operating_profit", "opm_percentage", "other_income",
        "interest", "depreciation", "profit_before_tax", "tax_percent", "net_profit", "eps_in_rs"
    ]
    
    annual_bs_fields = [
        "equity_capital", "reserves", "trade_payables_current", "borrowings",
        "other_liabilities", "total_liabilities", "total_equity", "fixed_assets",
        "cwip", "investments", "total_assets"
    ]
    
    annual_cf_fields = [
        "cash_from_operating_activity", "cash_from_investing_activity", "cash_from_financing_activity"
    ]
    
    # Filter data
    if frequency == "quarterly":
        fields = set(quarterly_fields)
    elif frequency == "yearly" or frequency == "annual" or frequency=="year":
        fields = set()
        st = statement_type.lower() if statement_type else ""
        if "income_statement" in st or "profit" in st or "loss" in st:
            fields.update(annual_pl_fields)
        if "balance_sheet" in st:
            fields.update(annual_bs_fields)
        if "cash_flow" in st or "cashflow" in st:
            fields.update(annual_cf_fields)
        if "unspecified" in st or not st:
            fields.update(annual_pl_fields)
            fields.update(annual_bs_fields)
            fields.update(annual_cf_fields)
        if not fields:
            fields.update(annual_pl_fields)  # default to PL fields for annual
    else:
        fields = set()
        st = statement_type.lower() if statement_type else ""
        if "income_statement" in st or "profit" in st or "loss" in st:
            fields.update(annual_pl_fields)
        if "balance_sheet" in st:
            fields.update(annual_bs_fields)
        if "cash_flow" in st or "cashflow" in st:
            fields.update(annual_cf_fields)
        if not fields:
            fields.update(annual_pl_fields)
            
    filtered = {k: v for k, v in data.items() if k in fields}

    return filtered


@router.post("/llm/target_companies", response_model=Dict[str, Any])
async def llm_target_companies(request: LLMQueryRequest):
    """Parse user query, fetch data, and generate answer with Azure LLM."""
    try:
        print("Step 1: Parsing user query with LLM")
        parsed = parse_query_and_get_companies(request.query)
        print("1st LLM returned:", parsed)
        if parsed.get("error"):
            raise HTTPException(status_code=500, detail=parsed.get("error"))

        # Extract intent
        intent = parsed.get("intent", {})
        statement_type = intent.get("statement_type", "unspecified")
        statement_frequency = intent.get("statement_frequency", "unspecified")
        period = intent.get("period", "unspecified")
        frequency = _determine_frequency(statement_frequency, statement_type, period)
        print(f"Determined frequency: {frequency}, statement_frequency: {statement_frequency}, statement_type: {statement_type}, period: {period}")

        # Fetch data for target companies and peers
        repo = SqliteRepository()
        all_data = {}

        target_companies = parsed.get("target_companies", {})
        include_peers = _should_include_peers(request.query)
        print("Step 2: Fetching data for target companies" + (" + peers" if include_peers else ""))
        for key, company in target_companies.items():
            scrip_code = company.get("scrip_code")
            if scrip_code:
                data = _fetch_company_data(repo, scrip_code, frequency, statement_type)
                all_data[company.get("company", key)] = data
                print(f"Fetched from {frequency}_table for scrip_code {scrip_code}: {data}")

            if include_peers:
                peers = company.get("peers", {})
                for p_key, peer in peers.items():
                    p_scrip = peer.get("scrip_code")
                    if p_scrip:
                        p_data = _fetch_company_data(repo, p_scrip, frequency, statement_type)
                        all_data[peer.get("company", p_key)] = p_data
                        print(f"Fetched from {frequency}_table for scrip_code {p_scrip}: {p_data}")

        # Generate answer using LLM
        print("Step 3: Generating answer with 2nd LLM")
        answer = generate_answer_from_data(request.query, all_data, statement_type, frequency)
        print("2nd LLM answer:", answer)
        
        # Save chat to database
        chat_id = str(uuid.uuid4())
        repo.save_chat(chat_id, request.query, answer)
        repo.close()
        
        return {
            "chat_id": chat_id,
            "answer": answer
        }

    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/chat-history", response_model=List[ChatHistoryResponse])
async def get_chat_history():
    """Get all chat history."""
    try:
        repo = SqliteRepository()
        chats = repo.get_chat_history()
        repo.close()
        
        # Format response with titles (first 50 chars of query)
        return [
            ChatHistoryResponse(
                chat_id=chat["chat_id"],
                user_query=chat["user_query"],
                response=chat["response"],
                created_at=chat["created_at"],
                title=chat["user_query"][:50] + ("..." if len(chat["user_query"]) > 50 else "")
            )
            for chat in chats
        ]
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/chat-history/{chat_id}", response_model=ChatHistoryResponse)
async def get_chat(chat_id: str):
    """Get a specific chat by ID."""
    try:
        repo = SqliteRepository()
        chat = repo.get_chat_by_id(chat_id)
        repo.close()
        
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        return ChatHistoryResponse(
            chat_id=chat["chat_id"],
            user_query=chat["user_query"],
            response=chat["response"],
            created_at=chat["created_at"],
            title=chat["user_query"][:50] + ("..." if len(chat["user_query"]) > 50 else "")
        )
    except HTTPException:
        raise
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))
