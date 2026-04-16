"""NLP-based company extraction module using BSE company list from Validation.csv.

This module provides deterministic, rule-based company extraction without LLM dependency.
It uses fuzzy matching and keyword extraction against the BSE company database.
"""

import re
import csv
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from difflib import SequenceMatcher


class CompanyExtractor:
    """Extract companies from user queries using NLP and fuzzy matching against BSE list."""
    
    def __init__(self):
        """Initialize with validation companies from BSE list."""
        self._companies: List[Dict[str, str]] = []
        self._load_validation_companies()
    
    def _load_validation_companies(self) -> None:
        """Load validation companies from Validation.csv."""
        validation_path = self._get_validation_csv_path()
        if not validation_path.exists():
            print(f"Warning: Validation CSV not found at {validation_path}")
            return
        
        with open(validation_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                self._companies.append({
                    "security_code": row.get("Security Code", "").strip(),
                    "issuer_name": row.get("Issuer Name", "").strip(),
                    "security_id": row.get("Security Id", "").strip(),
                    "security_name": row.get("Security Name", "").strip(),
                })
    
    def _get_validation_csv_path(self) -> Path:
        """Get the path to Validation.csv."""
        src_dir = Path(__file__).resolve().parents[1]  # points to src/
        return src_dir / "Data" / "Validation.csv"
    
    @staticmethod
    def _normalize_text(text: Optional[str]) -> str:
        """Normalize text for comparison."""
        if text is None:
            return ""
        normalized = text.strip().lower()
        # Remove common suffixes and special characters
        normalized = re.sub(r"\.|,|\(|\)|&", "", normalized)
        # Normalize 'ltd', 'limited', 'inc', etc.
        normalized = re.sub(r"\b(ltd|limited|inc|incorporated)\b", "", normalized)
        # Clean up whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized
    
    @staticmethod
    def _similarity_ratio(str1: str, str2: str) -> float:
        """Calculate similarity ratio between two strings (0.0 to 1.0)."""
        return SequenceMatcher(None, str1, str2).ratio()
    
    def _find_best_match(self, query_name: str, threshold: float = 0.6) -> Optional[Dict[str, str]]:
        """Find best matching company from BSE list using fuzzy matching."""
        normalized_query = self._normalize_text(query_name)
        
        if not normalized_query:
            return None
        
        best_match = None
        best_score = threshold
        
        for company in self._companies:
            issuer_normalized = self._normalize_text(company["issuer_name"])
            security_normalized = self._normalize_text(company["security_name"])
            code_normalized = self._normalize_text(company["security_id"])
            
            # Calculate similarity scores
            issuer_score = self._similarity_ratio(normalized_query, issuer_normalized)
            security_score = self._similarity_ratio(normalized_query, security_normalized)
            code_score = self._similarity_ratio(normalized_query, code_normalized)
            
            # Also check for substring matches (higher weight)
            if normalized_query in issuer_normalized or issuer_normalized in normalized_query:
                issuer_score = min(issuer_score + 0.15, 1.0)
            if normalized_query in security_normalized or security_normalized in normalized_query:
                security_score = min(security_score + 0.15, 1.0)
            if normalized_query in code_normalized or code_normalized in normalized_query:
                code_score = min(code_score + 0.15, 1.0)
            
            # Take the best score among all fields
            max_score = max(issuer_score, security_score, code_score)
            
            if max_score > best_score:
                best_score = max_score
                best_match = company
        
        return best_match
    
    def extract_companies_from_query(self, query: str) -> List[Dict[str, Any]]:
        """Extract companies from a user query.
        
        Returns a list of dictionaries with:
        - company: Original company name from query
        - matched: Whether a match was found
        - issuer_name: Matched BSE issuer name (if matched)
        - security_code: BSE security code (if matched)
        - security_id: BSE security ID / symbol (if matched)
        """
        if not query or not query.strip():
            return []
        
        # Extract potential company names using NLP techniques
        potential_names = self._extract_potential_company_names(query)
        
        results = []
        for name in potential_names:
            match = self._find_best_match(name, threshold=0.6)
            
            if match:
                results.append({
                    "company": name,
                    "matched": True,
                    "issuer_name": match["issuer_name"],
                    "security_code": match["security_code"],
                    "security_id": match["security_id"],
                })
            else:
                results.append({
                    "company": name,
                    "matched": False,
                    "issuer_name": None,
                    "security_code": None,
                    "security_id": None,
                })
        
        return results
    
    def _extract_potential_company_names(self, query: str) -> List[str]:
        """Extract potential company names from query using NLP patterns.
        
        Strategies:
        1. Look for capitalized words/phrases (likely company names)
        2. Look for words after keywords like "of", "for", "at", "from"
        3. Use BSE list as a dictionary to find exact/partial matches
        4. Extract proper nouns (all caps or Title Case sequences)
        """
        potential_names = set()
        
        # Strategy 1: Extract all capitalized sequences (likely proper nouns)
        # This pattern finds sequences of title-case words or all-caps words
        capitalized_pattern = r'\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*\b'
        for match in re.finditer(capitalized_pattern, query):
            word_seq = match.group(0).strip()
            # Filter out common non-company words
            if not self._is_common_word(word_seq) and len(word_seq) > 1:
                potential_names.add(word_seq)
        
        # Strategy 2: Extract words following specific prepositions
        # Pattern: "for/of/at/from/company X", "X limited/ltd"
        contextual_patterns = [
            r'(?:for|of|at|from|company|between)\s+([A-Za-z\s&]+?)(?:\s+(?:limited|ltd|inc|and)|\s+(?:is|was|has|have)|$)',
            r'([A-Za-z\s&]+?)\s+(?:limited|ltd|inc|incorporated)',
        ]
        for pattern in contextual_patterns:
            for match in re.finditer(pattern, query, re.IGNORECASE):
                name = match.group(1).strip()
                if not self._is_common_word(name) and len(name) > 1:
                    potential_names.add(name)
        
        # Strategy 3: Look for BSE company names directly in the query
        # Check if any company name (or part of it) exists in the query
        for company in self._companies:
            for field in ["issuer_name", "security_name", "security_id"]:
                company_name = company.get(field, "").strip()
                if not company_name:
                    continue
                # Check for exact or partial match (case-insensitive)
                pattern = r'\b' + re.escape(company_name) + r'\b'
                if re.search(pattern, query, re.IGNORECASE):
                    potential_names.add(company_name)
                
                # Also check for shorter versions (e.g., "TCS" for "Tata Consultancy Services")
                parts = company_name.split()
                if len(parts) > 1 and len(parts[0]) >= 2:
                    short_form = parts[0]
                    if re.search(r'\b' + re.escape(short_form) + r'\b', query, re.IGNORECASE):
                        potential_names.add(company_name)
        
        # Strategy 4: Extract known company symbols (all caps, 2-10 chars)
        symbol_pattern = r'\b([A-Z]{2,10})\b'
        for match in re.finditer(symbol_pattern, query):
            symbol = match.group(1)
            # Check if this symbol exists in BSE list
            for company in self._companies:
                if company["security_id"].upper() == symbol:
                    potential_names.add(company["issuer_name"])
                    break
        
        return list(potential_names)
    
    @staticmethod
    def _is_common_word(word: str) -> bool:
        """Check if a word is a common English word (not a company name)."""
        common_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'can',
            'could', 'should', 'may', 'might', 'must', 'shall', 'as', 'if', 'than',
            'that', 'this', 'these', 'those', 'what', 'which', 'who', 'why', 'how',
            'we', 'you', 'he', 'she', 'it', 'they', 'i', 'me', 'him', 'her', 'us',
            'them', 'my', 'your', 'his', 'her', 'its', 'our', 'their', 'all', 'each',
            'every', 'both', 'either', 'neither', 'some', 'any', 'no', 'none', 'not',
            'only', 'just', 'also', 'even', 'still', 'quite', 'so', 'such', 'because',
            'while', 'when', 'where', 'financial', 'data', 'report', 'statement',
            'analysis', 'query', 'information', 'please', 'show', 'compare', 'provide',
            'get', 'fetch', 'retrieve', 'find', 'give', 'tell', 'help', 'latest',
            'previous', 'current', 'new', 'old', 'last', 'next', 'year', 'month',
            'quarter', 'day', 'period', 'time', 'date', 'fiscal', 'annual',
            'quarterly', 'monthly', 'weekly', 'daily', 'revenue', 'profit', 'loss',
            'earnings', 'income', 'expense', 'cost', 'cash', 'flow', 'balance',
            'sheet', 'asset', 'liability', 'equity', 'ratio', 'metric', 'performance'
        }
        return word.lower() in common_words
    
    def parse_query_intent(self, query: str) -> Dict[str, Any]:
        """Parse query intent and extract financial parameters.
        
        Extracts:
        - statement_frequency: 'quarterly', 'annual', 'both', or 'unspecified'
        - statement_type: 'balance_sheet', 'cash_flow', 'income_statement', 'ratios', 'unspecified'
        - period: Specific period or 'unspecified'
        - time_horizon: Normalized window like 'latest', '2years', '5years', 'unspecified'
        - get_peer: Boolean indicating if peers are requested
        """
        query_lower = query.lower()
        
        # Detect statement frequency
        frequency = 'unspecified'
        if any(word in query_lower for word in ['quarterly', 'quarter', 'q1', 'q2', 'q3', 'q4', 'qtr']):
            frequency = 'quarterly'
        elif any(word in query_lower for word in ['annual', 'yearly', 'fy', 'financial year', 'year']):
            frequency = 'annual'
        elif any(word in query_lower for word in ['both quarterly and annual', 'quarterly and annual']):
            frequency = 'both'
        
        # Detect statement type
        statement_type = 'unspecified'
        if any(word in query_lower for word in ['balance sheet', 'assets', 'liabilities', 'equity']):
            statement_type = 'balance_sheet'
        elif any(word in query_lower for word in ['cash flow', 'cash flows', 'operating cash', 'free cash']):
            statement_type = 'cash_flow'
        elif any(word in query_lower for word in ['income statement', 'p&l', 'profit and loss', 'revenue', 'net profit', 'earnings']):
            statement_type = 'income_statement'
        elif any(word in query_lower for word in ['ratio', 'ratios', 'roa', 'roe', 'margin', 'turnover']):
            statement_type = 'ratios'
        
        # Detect time horizon
        time_horizon = 'unspecified'
        if any(word in query_lower for word in ['latest', 'most recent', 'recent']):
            time_horizon = 'latest'
        elif '5 year' in query_lower or '5year' in query_lower or '5-year' in query_lower:
            time_horizon = '5years'
        elif '3 year' in query_lower or '3year' in query_lower or '3-year' in query_lower:
            time_horizon = '3years'
        elif '2 year' in query_lower or '2year' in query_lower or '2-year' in query_lower:
            time_horizon = '2years'
        elif 'historical' in query_lower or 'trend' in query_lower or 'cagr' in query_lower:
            time_horizon = 'historical'
        
        # Detect period (specific time frame)
        period = 'unspecified'
        period_patterns = [
            (r'fy(\d{4})[- ]?(\d{2,4})', 'fiscal year'),
            (r'q(\d)[- ]?(\d{4})', 'quarter'),
            (r'(?:latest|last|previous)\s+quarter', 'latest quarter'),
            (r'(?:latest|last|previous)\s+(?:year|financial year)', 'latest year'),
            (r'all quarters? of.*(?:year|fy)', 'all quarters of latest year'),
        ]
        for pattern, label in period_patterns:
            if re.search(pattern, query_lower):
                period = label
                break
        
        # Detect if peers are requested
        get_peer = any(word in query_lower for word in [
            'peer', 'peers', 'competitor', 'competitors', 'industry',
            'benchmark', 'compared to', 'compare with', 'vs', 'versus',
            'similar company', 'similar companies', 'like', 'comparable'
        ])
        
        return {
            "statement_frequency": frequency,
            "statement_type": statement_type,
            "period": period,
            "time_horizon": time_horizon,
            "get_peer": get_peer,
        }


def parse_query_and_get_companies_nlp(query: str) -> Tuple[Dict[str, Any], str]:
    """Main function to replace LLM-based company extraction.
    
    Uses NLP-based parsing to extract companies and query intent from user query.
    Returns structured response compatible with existing llm_route.py.
    
    Returns:
        Tuple of (parsed_response, system_prompt_used)
        Where parsed_response has format:
        {
            "intent": {...},
            "target_companies": {
                "1": {"company": "...", "symbol": "...", "scrip_code": "...", "industry": "..."},
                ...
            }
        }
    """
    if not query or not query.strip():
        return {
            "error": "Query must not be empty."
        }, ""
    
    extractor = CompanyExtractor()
    
    # Extract companies from query
    extracted_companies = extractor.extract_companies_from_query(query)
    
    # Parse query intent
    intent = extractor.parse_query_intent(query)
    
    # Build target_companies dictionary
    target_companies = {}
    company_index = 1
    
    for company_info in extracted_companies:
        if company_info["matched"]:
            target_companies[str(company_index)] = {
                "company": company_info["issuer_name"],
                "symbol": company_info["security_id"],
                "scrip_code": company_info["security_code"],
                "industry": "unspecified",  # Industry not available from BSE list
            }
            company_index += 1
    
    # If no companies found, return error
    if not target_companies:
        return {
            "error": f"No companies found in query. Extracted: {[c['company'] for c in extracted_companies]}"
        }, ""
    
    # Build final response
    response = {
        "intent": intent,
        "target_companies": target_companies,
    }
    
    system_prompt_used = (
        "NLP-based company extraction using BSE (Validation.csv) company list. "
        "No LLM dependency. Uses fuzzy matching and pattern recognition."
    )
    
    return response, system_prompt_used
