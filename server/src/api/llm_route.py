from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime
import uuid
import json
import os
from pathlib import Path

from service.analysis_service import parse_query_and_get_companies, generate_answer_from_data
from repository.sqlite_repository import SqliteRepository

router = APIRouter()


def write_llm_log(user_query: str, llm_prompt: str, llm_response: str, db_data: Dict[str, Any], data_passed_to_llm: Dict[str, Any], final_prompt: str, final_response: str, peer_extraction_log: str = ""):
    """Write detailed LLM interaction logs to timestamped file."""
    try:
        # Create logs directory if it doesn't exist
        logs_dir = Path(__file__).parent.parent / "logs"
        logs_dir.mkdir(exist_ok=True)

        # Generate timestamp for filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_filename = f"Log-{timestamp}.log"
        log_filepath = logs_dir / log_filename

        # Format the log content
        log_content = f"""=== LLM TARGET COMPANIES LOG ===
Timestamp: {datetime.now().isoformat()}
Log File: {log_filename}

1. USER QUERY:
{user_query}

2. INITIAL LLM PROMPT (Query Parsing):
{llm_prompt}

3. INITIAL LLM RESPONSE (Parsed Query):
{llm_response}

4. PEER EXTRACTION LOG:
{peer_extraction_log}

5. DATA FETCHED FROM DATABASE:
{json.dumps(db_data, indent=2)}

6. DATA PASSED TO LLM:
{json.dumps(data_passed_to_llm, indent=2)}

7. FINAL PROMPT GIVEN TO LLM:
{final_prompt}

8. FINAL RESPONSE FROM LLM:
{final_response}

=== END LOG ===
"""

        # Write to file
        with open(log_filepath, 'w', encoding='utf-8') as f:
            f.write(log_content)

        print(f"LLM log written to: {log_filepath}")

    except Exception as e:
        print(f"Error writing LLM log: {str(e)}")


def get_actual_initial_prompt() -> str:
    """Get the actual initial prompt used for query parsing."""
    # This should match the system prompt in parse_query_and_get_companies
    return """You are a Senior Financial Analyst and Data Extraction Expert. Your task is to analyze a user query for financial data extraction.

First, break down the query into key components:
- **statement_frequency**: 'quarterly', 'annual', or 'unspecified'.
- **statement_type**: 'balance_sheet', 'cash_flow', 'income_statement', 'ratios', or 'unspecified'.
- **period**: Specific period like 'latest quarter', 'Q3 2023', or 'unspecified'.
- **target_companies**: List of company names mentioned.
- **industries**: Any industries mentioned.
- **other_requirements**: Any other specific requirements or questions.
- **get_peer**: Set to true if the query requires peer company analysis/comparison, false otherwise.

Then, based on the breakdown, generate a structured JSON response identifying target companies.
If get_peer is true, the system will automatically fetch appropriate peers from the database.
Ensure scrip_codes are accurate BSE codes.

Return strictly valid JSON with no additional text.

JSON Schema:
{
  "intent": {
    "statement_frequency": "string",
    "statement_type": "string",
    "period": "string",
    "get_peer": boolean
  },
  "target_companies": {
    "1": {
      "company": "company_name",
      "symbol": "company_symbol",
      "scrip_code": "company_scrip_code",
      "industry": "company_industry"
    }
  }
}
"""


def get_actual_final_prompt(query: str, data: Dict[str, Any], statement_type: str, frequency: str) -> str:
    """Get the actual final prompt used for answer generation."""
    system_prompt = f"""You are a Financial Analyst. Answer the user's query using the provided financial data.
The data is for {frequency} financial statements, including {statement_type.replace('_', ' ')} metrics where available.

Provide a clear, concise answer to the query. If data is missing for some companies, note that."""
    
    user_prompt = f"Query: {query}\n\nData: {json.dumps(data, indent=2)}"
    
    return f"{system_prompt}\n\n{user_prompt}"

class LLMQueryRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None


class ChatHistoryResponse(BaseModel):
    chat_id: str
    title: str  # Display title for chat history
    created_at: str
    last_message: Optional[str] = None


class ChatMessageResponse(BaseModel):
    id: int
    sequence_number: int
    role: str
    content: str
    created_at: str


class ConversationResponse(BaseModel):
    chat_id: str
    title: str
    created_at: str
    messages: List[ChatMessageResponse]


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


def _requires_historical_data(query: str) -> bool:
    """Check if the query requires historical/trend data."""
    q = (query or "").strip().lower()
    if not q:
        return False
    historical_keywords = ["historical", "5y", "5 year", "trend", "cagr", "growth", "over time", "past", "fy", "year"]
    return any(keyword in q for keyword in historical_keywords)


def _fetch_company_data(repo: SqliteRepository, scrip_code: str, frequency: str, statement_type: str, query: str = "") -> Dict[str, Any]:
    """Fetch data for a company and filter fields based on frequency and statement_type."""
    requires_historical = _requires_historical_data(query)
    
    if requires_historical:
        if frequency == "annual":
            data_list = repo.get_historical_annual_data(scrip_code, limit=5)
        else:
            data_list = repo.get_historical_quarterly_data(scrip_code, limit=5)
        
        if data_list:
            # Return as a list under the company key
            return {scrip_code: data_list}
        else:
            # Fallback to latest if no historical
            if frequency == "annual":
                data = repo.get_latest_annual_data(scrip_code)
            else:
                data = repo.get_latest_quarterly_data(scrip_code)
            return {scrip_code: [data]} if data else {}
    else:
        if frequency == "annual":
            data = repo.get_latest_annual_data(scrip_code)
        else:
            data = repo.get_latest_quarterly_data(scrip_code)
        
        if not data:
            return {}

    # Define field sets using DB column names
    quarterly_fields = [
        "currency","level_of_rounding",
        "sales", "expenses", "operating_profit", "opm_percentage", "other_income",
        "cost_of_materials_consumed", "employee_benefit_expense", "other_expenses",
        "interest", "depreciation", "profit_before_tax", "current_tax", "deferred_tax",
        "tax", "tax_percent", "net_profit", "eps_in_rs"
    ]
    
    annual_pl_fields = [
        "currency","level_of_rounding",
        "sales", "expenses", "operating_profit", "opm_percentage", "other_income",
        "interest", "depreciation", "profit_before_tax", "tax_percent", "net_profit", "eps_in_rs"
    ]
    
    annual_bs_fields = [
        "currency","level_of_rounding",
        "equity_capital", "reserves", "trade_payables_current", "borrowings",
        "other_liabilities", "total_liabilities", "total_equity", "fixed_assets",
        "cwip", "investments", "total_assets"
    ]
    
    annual_cf_fields = [
        "currency","level_of_rounding",
        "cash_from_operating_activity", "cash_from_investing_activity", "cash_from_financing_activity"
    ]
    
    # Filter data
    if requires_historical:
        # For historical, return the list as is, but filter fields
        if isinstance(data, list):
            filtered_list = []
            for item in data:
                filtered = {k: v for k, v in item.items() if k in quarterly_fields}
                filtered_list.append(filtered)
            return {scrip_code: filtered_list}
        else:
            return {}
    else:
        # For single data
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

        return {scrip_code: filtered}


@router.post("/llm/target_companies", response_model=Dict[str, Any])
async def llm_target_companies(request: LLMQueryRequest):
    """Parse user query, fetch data, and generate answer with Azure LLM."""
    try:
        repo = SqliteRepository()

        # Create or validate conversation
        if request.conversation_id is None:
            conversation_id = repo.create_conversation()
        else:
            conversation_id = request.conversation_id
            if not repo.conversation_exists(conversation_id):
                repo.close()
                raise HTTPException(status_code=404, detail="Conversation not found")

        chat_id = str(conversation_id)

        # Save the incoming user message inside the conversation
        repo.save_message(conversation_id, "user", request.query)

        # Initialize log variables
        user_query = request.query
        initial_llm_prompt = get_actual_initial_prompt()
        initial_llm_response = ""
        db_fetched_data = {}
        data_passed_to_llm = {}
        final_llm_prompt = ""
        peer_extraction_log = ""

        # Step 1: Parse user query
        print("Step 1: Parsing user query with LLM")
        parsed, initial_llm_prompt, peer_extraction_log = parse_query_and_get_companies(request.query)
        print("1st LLM returned:", parsed)

        # Store initial LLM interaction for logging
        initial_llm_response = json.dumps(parsed)

        # Log Step 1 - Query parsing
        repo.save_detailed_log(
            chat_id=chat_id,
            step_name="Query Parsing",
            input_data=json.dumps({"user_query": request.query}),
            output_data=json.dumps(parsed)
        )

        if parsed.get("error"):
            raise HTTPException(status_code=500, detail=parsed.get("error"))

        # Extract intent
        intent = parsed.get("intent", {})
        statement_type = intent.get("statement_type", "unspecified")
        statement_frequency = intent.get("statement_frequency", "unspecified")
        period = intent.get("period", "unspecified")
        get_peer = intent.get("get_peer", False)
        frequency = _determine_frequency(statement_frequency, statement_type, period)
        print(f"Determined frequency: {frequency}, statement_frequency: {statement_frequency}, statement_type: {statement_type}, period: {period}, get_peer: {get_peer}")

        # Step 2: Fetch data for target companies and peers
        print("Step 2: Fetching data for target companies" + (" + peers" if get_peer else ""))
        all_data = {}
        target_companies = parsed.get("target_companies", {})

        db_fetch_log = {
            "frequency": frequency,
            "statement_type": statement_type,
            "companies_requested": list(target_companies.keys()),
            "get_peer": get_peer,
            "fetched_data": {}
        }

        for key, company in target_companies.items():
            scrip_code = company.get("scrip_code")
            if scrip_code:
                data = _fetch_company_data(repo, scrip_code, frequency, statement_type, request.query)
                all_data[company.get("company", key)] = data
                db_fetch_log["fetched_data"][company.get("company", key)] = {
                    "scrip_code": scrip_code,
                    "frequency": frequency,
                    "data": data
                }
                print(f"Fetched from {frequency}_table for scrip_code {scrip_code}: {data}")

            if get_peer:
                peers = company.get("peers", {})
                for p_key, peer in peers.items():
                    p_scrip = peer.get("scrip_code")
                    if p_scrip:
                        p_data = _fetch_company_data(repo, p_scrip, frequency, statement_type, request.query)
                        all_data[peer.get("company", p_key)] = p_data
                        db_fetch_log["fetched_data"][peer.get("company", p_key)] = {
                            "scrip_code": p_scrip,
                            "frequency": frequency,
                            "is_peer": True,
                            "data": p_data
                        }
                        print(f"Fetched from {frequency}_table for peer scrip_code {p_scrip}: {p_data}")

        # Store DB fetched data for logging
        db_fetched_data = db_fetch_log

        # Log Step 2 - Database fetching
        repo.save_detailed_log(
            chat_id=chat_id,
            step_name="Database Fetch",
            input_data=json.dumps({
                "parsed_query": parsed,
                "frequency": frequency,
                "statement_type": statement_type,
                "target_companies": list(target_companies.keys())
            }),
            output_data=json.dumps(db_fetch_log)
        )

        # Step 3: Generate answer using LLM
        print("Step 3: Generating answer with 2nd LLM")

        # Prepare the EXACT data being sent to LLM
        system_prompt = f"""You are a Financial Analyst. Answer the user's query using the provided financial data.
The data is for {frequency} financial statements, including {statement_type.replace('_', ' ')} metrics where available.

Provide a clear, concise answer to the query. If data is missing for some companies, note that."""

        user_prompt = f"Query: {request.query}\n\nData: {json.dumps(all_data, indent=2)}"

        final_llm_prompt = get_actual_final_prompt(request.query, all_data, statement_type, frequency)

        # Store data passed to LLM for logging
        data_passed_to_llm = all_data

        answer = generate_answer_from_data(request.query, all_data, statement_type, frequency)
        print("2nd LLM answer:", answer)

        # Store final LLM response for logging
        final_llm_response = answer

        # Save assistant message inside the same conversation
        repo.save_message(conversation_id, "llm", answer)

        # Log Step 3 - EXACT LLM input and output
        repo.save_detailed_log(
            chat_id=chat_id,
            step_name="Answer Generation (LLM)",
            input_data=json.dumps({
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "query": request.query,
                "data_sent": all_data,
                "statement_type": statement_type,
                "frequency": frequency
            }, default=str),
            output_data=json.dumps({
                "llm_response": answer,
                "timestamp": datetime.now().isoformat()
            })
        )

        repo.close()

        # Write comprehensive log to file
        write_llm_log(
            user_query=user_query,
            llm_prompt=initial_llm_prompt,
            llm_response=initial_llm_response,
            db_data=db_fetched_data,
            data_passed_to_llm=data_passed_to_llm,
            final_prompt=final_llm_prompt,
            final_response=final_llm_response,
            peer_extraction_log=peer_extraction_log if 'peer_extraction_log' in locals() else ""
        )

        return {
            "chat_id": chat_id,
            "answer": answer
        }

    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/chat-history", response_model=List[ChatHistoryResponse])
async def get_chat_history():
    """Get all chat conversations."""
    try:
        repo = SqliteRepository()
        chats = repo.get_conversation_list()
        repo.close()

        return [
            ChatHistoryResponse(
                chat_id=str(chat["chat_id"]),
                created_at=chat.get("last_updated") or chat["created_at"],
                title=(chat.get("first_message") or "New conversation")[:50] + (
                    "..." if chat.get("first_message") and len(chat.get("first_message")) > 50 else ""
                ),
                last_message=chat.get("last_message"),
            )
            for chat in chats
        ]
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/chat-history/{chat_id}", response_model=ConversationResponse)
async def get_chat(chat_id: str):
    """Get a specific conversation by ID."""
    try:
        conversation_id = int(chat_id)
        repo = SqliteRepository()
        if not repo.conversation_exists(conversation_id):
            repo.close()
            raise HTTPException(status_code=404, detail="Chat not found")

        conversation = repo.get_conversation(conversation_id)
        messages = repo.get_conversation_messages(conversation_id)
        repo.close()

        title = "Chat"
        if messages:
            title = messages[0]["content"][:50] + ("..." if len(messages[0]["content"]) > 50 else "")

        return ConversationResponse(
            chat_id=chat_id,
            created_at=conversation["created_at"],
            title=title,
            messages=[
                ChatMessageResponse(
                    id=msg["id"],
                    sequence_number=msg["sequence_number"],
                    role=msg["role"],
                    content=msg["content"],
                    created_at=msg["created_at"],
                )
                for msg in messages
            ],
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chat id")
    except HTTPException:
        raise
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/detailed-logs/{chat_id}")
async def get_detailed_logs(chat_id: str):
    """Get detailed input/output logs for a specific chat."""
    try:
        repo = SqliteRepository()
        logs = repo.get_detailed_logs(chat_id)
        repo.close()
        
        if not logs:
            raise HTTPException(status_code=404, detail="No detailed logs found for this chat")
        
        return {
            "chat_id": chat_id,
            "logs": logs,
            "total_steps": len(logs)
        }
    except HTTPException:
        raise
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))
