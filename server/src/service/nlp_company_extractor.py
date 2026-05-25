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
    def _is_generic_candidate(candidate: str) -> bool:
        normalized = re.sub(r"\s+", " ", candidate.strip().lower())
        words = normalized.split()
        generic_terms = {
            'peer', 'peers', 'competitor', 'competitors', 'company', 'companies',
            'it', 'its', 'their', 'them', 'they', 'we', 'us', 'our', 'you', 'your',
            'report', 'reports', 'analysis', 'analyses', 'results', 'financials',
            'performance', 'compare', 'comparison', 'benchmark', 'benchmarks',
            'latest', 'recent', 'previous', 'current', 'last', 'quarter', 'year',
            'earnings', 'income', 'revenue', 'profit', 'loss', 'cash', 'flow',
            'available', 'data', 'question', 'comparative', 'comparitive', 'analysis',
        }
        if any(word in generic_terms for word in words):
            return True
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
        
        # Determine if this is a multi-company/comparison query
        multi_company = any(word in query.lower() for word in [" and ", " vs ", " versus ", " between ", "compare "])

        results = []
        seen_symbols = set()
        for name in potential_names:
            if self._is_generic_candidate(name):
                continue

            # For simple queries (single word), use lower threshold for fuzzy matching
            is_simple_query = len(name.split()) == 1
            threshold = 0.5 if is_simple_query else 0.6

            match = self._find_best_match(name, threshold=threshold)

            if match:
                symbol = match["security_id"]
                if symbol in seen_symbols:
                    continue
                seen_symbols.add(symbol)
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

            # If not a multi-company query, only return the first valid match
            if not multi_company and results:
                break

        return results
    
    def _extract_potential_company_names(self, query: str) -> List[str]:
        """Extract potential company names from query using NLP patterns.
        
        Strategies:
        1. Look for capitalized words/phrases (likely company names)
        2. Look for words after keywords like "of", "for", "at", "from"
        3. Use BSE list as a dictionary to find exact/partial matches
        4. Extract proper nouns (all caps or Title Case sequences)
        """
        potential_names: List[str] = []
        seen_candidates = set()

        def add_candidate(candidate: str) -> None:
            normalized = self._normalize_text(candidate)
            if normalized and normalized not in seen_candidates:
                potential_names.append(candidate)
                seen_candidates.add(normalized)

        # Strategy 5 (First): Extract company names from report/earnings queries
        # Pattern: "report for swiggy", "earnings for [company]", "generate financial analysis for X"
        report_patterns = [
            r'(?:report|earnings|financial|results|analysis|performance|review)\s+(?:for|of|on)\s+([A-Za-z\s&]+?)(?:\s+for|\s+in|[\.\?\!]|$)',
            r'(?:generate|create|show|provide|get|fetch)\s+(?:report|analysis|earnings|financial)\s+(?:for|of|on)\s+([A-Za-z\s&]+?)(?:$|[\.\?\!])',
        ]
        for pattern in report_patterns:
            for match in re.finditer(pattern, query, re.IGNORECASE):
                company_name = match.group(1).strip()
                if company_name and len(company_name) > 1:
                    cleaned = self._clean_company_candidate(company_name)
                    if cleaned:
                        add_candidate(cleaned)

        # Strategy 0: Extract direct compare/between company pairs first
        compare_patterns = [
            r'compare\s+(?:how|what|whether|the)?\s*([^\.\?\!]*?)\s+(?:and|vs|versus)\s+([^\.\?\!]*?)(?:\'s|’s)?(?:\s+(?:latest|recent|last|annual|quarterly|results|financial|performance|trends|year|period|outlook|based|in|with|for|on|using|across|over|within|about|regarding|concerning|during|amid|amidst|after|before|when|while|have|has|had)\b|[\.\?\!]|$)',
            r'between\s+([^\.\?\!]*?)\s+and\s+([^\.\?\!]*?)(?:\'s|’s)?(?:\s+(?:latest|recent|last|annual|quarterly|results|financial|performance|trends|year|period|outlook|based|in|with|for|on|using|across|over|within|about|regarding|concerning|during|amid|amidst|after|before|when|while|have|has|had)\b|[\.\?\!]|$)',
        ]
        for pattern in compare_patterns:
            for match in re.finditer(pattern, query, re.IGNORECASE):
                first = self._clean_company_candidate(match.group(1) or "")
                second = self._clean_company_candidate(match.group(2) or "")
                if first:
                    add_candidate(first)
                if second:
                    add_candidate(second)

        # Strategy 1: Extract all capitalized sequences (likely proper nouns)
        # This pattern finds sequences of title-case words or all-caps words
        capitalized_pattern = r'\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*\b'
        for match in re.finditer(capitalized_pattern, query):
            word_seq = match.group(0).strip()
            if len(word_seq) <= 1:
                continue

            cleaned = self._clean_company_candidate(word_seq)
            if cleaned and cleaned != word_seq:
                if self._is_company_phrase_in_validation(cleaned) or self._is_valid_symbol(cleaned):
                    add_candidate(cleaned)
                    continue

            words = word_seq.split()
            if len(words) == 1:
                # Allow single-word candidates only if it's a validated company name or symbol.
                if word_seq.isupper() and 2 <= len(word_seq) <= 10:
                    if not self._is_common_word(word_seq):
                        if any(company["security_id"].upper() == word_seq for company in self._companies):
                            add_candidate(word_seq)
                elif self._is_company_phrase_in_validation(word_seq):
                    add_candidate(word_seq)
            else:
                if self._is_company_phrase_in_validation(word_seq):
                    add_candidate(word_seq)
                else:
                    explicit = self._extract_explicit_company_name(word_seq)
                    if explicit and self._is_company_phrase_in_validation(explicit):
                        add_candidate(explicit)
        
        # Strategy 2: Extract words following specific prepositions
        # Pattern: "for/of/at/from/company X", "X limited/ltd"
        contextual_patterns = [
            r'(?:for|of|at|from|company|between)\s+([A-Za-z\s&]+?)(?:\s+(?:limited|ltd|inc|and|over|for|on|about|with|during|through|via|from|in|by)|$)',
            r'([A-Za-z\s&]+?)\s+(?:limited|ltd|inc|incorporated)',
        ]
        for pattern in contextual_patterns:
            for match in re.finditer(pattern, query, re.IGNORECASE):
                name = match.group(1).strip()
                if not self._is_common_word(name) and len(name) > 1 and self._is_company_phrase_in_validation(name):
                    add_candidate(name)

        # Safe token fallback: capture company abbreviations and short names such as HCL or Hexaware.
        token_pattern = r'\b([A-Za-z]{3,10})\b'
        for match in re.finditer(token_pattern, query):
            token = match.group(1).strip()
            if self._is_common_word(token):
                continue
            if self._is_company_phrase_in_validation(token):
                add_candidate(token)

        # Strategy 3: Look for BSE company names directly in the query
        # Check if any company name (or part of it) exists in the query
        prefix_counts: Dict[str, int] = {}
        for company in self._companies:
            issuer_name = self._normalize_text(company.get("issuer_name", ""))
            parts = issuer_name.split()
            if len(parts) >= 2:
                prefix = " ".join(parts[:2])
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

        for company in self._companies:
            for field in ["issuer_name", "security_name", "security_id"]:
                company_name = company.get(field, "").strip()
                if not company_name:
                    continue
                if len(company_name.split()) == 1:
                    # Avoid matching single-word issuer/symbol values directly here,
                    # as they can be generic tokens like energy or bank.
                    continue
                # Check for exact or partial match (case-insensitive)
                pattern = r'\b' + re.escape(company_name) + r'\b'
                if re.search(pattern, query, re.IGNORECASE):
                    add_candidate(company_name)
                
                # Also check for shorter versions only when the first two words appear together.
                # Only add if the prefix is unique, otherwise it may match multiple companies.
                parts = company_name.split()
                if len(parts) > 1:
                    short_form = parts[0]
                    second_word = parts[1]
                    if len(short_form) >= 3 and len(second_word) >= 3:
                        prefix = self._normalize_text(f"{short_form} {second_word}")
                        if prefix_counts.get(prefix, 0) == 1 and re.search(
                            r'\b' + re.escape(short_form) + r'\s+' + re.escape(second_word) + r'\b',
                            query,
                            re.IGNORECASE,
                        ):
                            add_candidate(company_name)

        # Strategy 3b: Avoid broad first-word extraction from company names.
        # We rely on explicit company names, symbols, or validated phrase matches.

        # Strategy 3c: Avoid false positives from known query terms by validating against company list
        validated_names = []
        validated_set = set()
        for name in potential_names:
            if len(name.split()) == 1 and not self._is_company_phrase_in_validation(name) and not self._is_valid_symbol(name):
                continue
            normalized_name = self._normalize_text(name)
            if normalized_name and normalized_name not in validated_set:
                validated_names.append(name)
                validated_set.add(normalized_name)
        potential_names = validated_names

        # Strategy 4: Extract known company symbols (all caps, 2-10 chars)
        symbol_pattern = r'\b([A-Z]{2,10})\b'
        for match in re.finditer(symbol_pattern, query):
            symbol = match.group(1)
            if self._is_common_word(symbol):
                continue
            if not self._is_valid_symbol(symbol):
                continue
            # Check if this symbol exists in BSE list
            for company in self._companies:
                if company["security_id"].upper() == symbol:
                    add_candidate(company["issuer_name"])
                    break
        
        # Deduplicate candidate names in a case-insensitive way
        filtered_candidates = []
        for name in potential_names:
            if any(
                name != other and self._is_subphrase(name, other)
                for other in potential_names
            ):
                continue
            filtered_candidates.append(name)

        return filtered_candidates

    def _is_company_phrase_in_validation(self, phrase: str) -> bool:
        normalized_phrase = self._normalize_text(phrase)
        if not normalized_phrase:
            return False

        tokens = normalized_phrase.split()
        if len(tokens) == 1:
            if self._is_valid_symbol(normalized_phrase):
                return True
            if len(normalized_phrase) < 3:
                return False

            match_count = 0
            for company in self._companies:
                for field in ["issuer_name", "security_name", "security_id"]:
                    value = company.get(field, "")
                    if not value:
                        continue
                    normalized_value = self._normalize_text(value)
                    if not normalized_value:
                        continue
                    if re.search(r'\b' + re.escape(normalized_phrase) + r'\b', normalized_value):
                        match_count += 1
                        break
            return match_count > 0

        for company in self._companies:
            for field in ["issuer_name", "security_name", "security_id"]:
                value = company.get(field, "")
                if not value:
                    continue
                normalized_value = self._normalize_text(value)
                if not normalized_value:
                    continue
                if normalized_phrase == normalized_value:
                    return True
                if re.search(r'\b' + re.escape(normalized_phrase) + r'\b', normalized_value):
                    return True
        return False

    def _is_valid_symbol(self, token: str) -> bool:
        normalized = token.strip().upper()
        if not normalized:
            return False
        return any(company["security_id"].upper() == normalized for company in self._companies)

    def _is_subphrase(self, shorter: str, longer: str) -> bool:
        shorter_tokens = shorter.lower().split()
        longer_tokens = longer.lower().split()
        if len(shorter_tokens) >= len(longer_tokens):
            return False
        for idx in range(len(longer_tokens) - len(shorter_tokens) + 1):
            if longer_tokens[idx:idx + len(shorter_tokens)] == shorter_tokens:
                return True
        return False

    def _extract_explicit_company_name(self, text: str) -> Optional[str]:
        normalized_text = self._normalize_text(text)
        if not normalized_text:
            return None

        # Check explicit symbol matches first.
        for company in self._companies:
            symbol = company.get("security_id", "").strip()
            if symbol and re.search(r'\b' + re.escape(symbol) + r'\b', text, re.IGNORECASE):
                return symbol

        # Check explicit issuer/security names in the candidate.
        for company in self._companies:
            for field in ["issuer_name", "security_name"]:
                value = company.get(field, "").strip()
                if value and re.search(r'\b' + re.escape(value) + r'\b', text, re.IGNORECASE):
                    return value

        # Scan trailing segments for valid company phrases or symbols.
        segments = re.split(
            r'\b(?:for|of|on|using|through|across|over|within|based on|with|about|regarding|concerning|considering|amid|amidst|after|before|during)\b|[,;:\\n]',
            text,
            flags=re.IGNORECASE,
        )
        for segment in reversed(segments):
            candidate = segment.strip(" '\".?!,;:-")
            if not candidate:
                continue
            if self._is_valid_symbol(candidate) or self._is_company_phrase_in_validation(candidate):
                return candidate

        # Try suffixes of the segment to recover a company phrase.
        words = re.findall(r"[A-Za-z0-9&]+", normalized_text)
        for start in range(len(words)):
            suffix = " ".join(words[start:])
            if self._is_company_phrase_in_validation(suffix):
                return suffix

        return None

    def _clean_company_candidate(self, candidate: str) -> str:
        candidate = candidate.strip(" '\".?!,;:-")
        if not candidate:
            return ""

        candidate = re.sub(r'^(?:how|what|whether|the|their)\s+', "", candidate, flags=re.IGNORECASE)

        parts = re.split(
            r"\b(?:like|such as|including|especially|among|with|along with|via)\b",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = parts[-1].strip()

        candidate = re.sub(
            r'^(?:the\s+)?(?:results|performance|financials|figures|numbers|reported|disclosures|data)(?:\s+of)?\s+',
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(
            r'[,;:].*$',
            "",
            candidate,
            flags=re.IGNORECASE,
        )

        if self._is_generic_candidate(candidate):
            return ""

        explicit = self._extract_explicit_company_name(candidate)
        if explicit:
            return explicit.strip(" '\".?!,;:-")

        candidate = re.sub(
            r'\b(?:for|of|about|using|through|across|over|within|based on|with)\s+([A-Za-z0-9&\.\- ]+)$',
            r'\1',
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(
            r'\b(?:on|for|about|regarding|concerning|in|during|over|with|based on|considering|amid|amidst|after|before|using|across|within|have|has|had|their|reported|figures|numbers|disclosures|periods?)\b.*$',
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = candidate.strip(" '\".?!,;:-")
        return candidate

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

            if normalized_query == issuer_normalized.split()[0] or normalized_query == security_normalized.split()[0]:
                issuer_score = max(issuer_score, 0.95)
                security_score = max(security_score, 0.95)
            
            # Prefer whole-word matches over weak substring-only hits.
            if re.search(r'\b' + re.escape(normalized_query) + r'\b', issuer_normalized):
                issuer_score = min(issuer_score + 0.25, 1.0)
            if re.search(r'\b' + re.escape(normalized_query) + r'\b', security_normalized):
                security_score = min(security_score + 0.25, 1.0)
            if re.search(r'\b' + re.escape(normalized_query) + r'\b', code_normalized):
                code_score = min(code_score + 0.25, 1.0)

            if normalized_query in issuer_normalized or issuer_normalized in normalized_query:
                issuer_score = min(issuer_score + 0.10, 1.0)
            if normalized_query in security_normalized or security_normalized in normalized_query:
                security_score = min(security_score + 0.10, 1.0)
            if normalized_query in code_normalized or code_normalized in normalized_query:
                code_score = min(code_score + 0.10, 1.0)

            if normalized_query in code_normalized and not re.search(r'\b' + re.escape(normalized_query) + r'\b', code_normalized):
                code_score = max(code_score - 0.15, 0.0)
            if normalized_query in issuer_normalized and not re.search(r'\b' + re.escape(normalized_query) + r'\b', issuer_normalized):
                issuer_score = max(issuer_score - 0.15, 0.0)
            if normalized_query in security_normalized and not re.search(r'\b' + re.escape(normalized_query) + r'\b', security_normalized):
                security_score = max(security_score - 0.15, 0.0)

            # Take the best score among all fields
            max_score = max(issuer_score, security_score, code_score)
            
            if max_score > best_score:
                best_score = max_score
                best_match = company
        
        return best_match
    
    @staticmethod
    def _is_common_word(word: str) -> bool:
        """Check if a word is a common English word (not a company name)."""
        common_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'can',
            'could', 'should', 'may', 'might', 'must', 'shall', 'as', 'if', 'than',
            'that', 'this', 'these', 'those', 'what', 'which', 'who', 'why', 'how',
            'it', 'based', 'considering', 'likely', 'better', 'next', 'coming',
            'outlook', 'headwinds', 'industry', 'pressures', 'uncertainty', 'volatility',
            'demand', 'growth', 'macro', 'macroeconomic', 'positioned', 'manage',
            'managing', 'compare', 'comparison', 'benchmark', 'results', 'performance',
            'global', 'risk', 'risks', 'budget', 'spending', 'recent', 'latest',
            'trend', 'trends', 'annual', 'quarterly',
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
            'available', 'question', 'comparative', 'comparitive',
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
        elif re.search(r'\b(?:financial year|fy|annual|yearly|past year|last year|full year|year ended|year-on-year|yoy)\b', query_lower):
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
        elif any(word in query_lower for word in ['risk', 'resilience', 'resilient', 'vulnerable', 'vulnerability', 'downturn', 'withstand', 'headwind', 'headwinds', 'pressure', 'weakness', 'shocks', 'downgrade', 'uncertain', 'uncertainty']):
            statement_type = 'risk'
        
        # Detect time horizon
        time_horizon = 'unspecified'
        if 'last four quarters' in query_lower or 'last 4 quarters' in query_lower or 'four quarters' in query_lower:
            time_horizon = '4quarters'
        elif re.search(r"\b(?:last|latest|most recent|previous|past|prior)\s+(?:two|2)\s+(?:financial\s+years?|years?|fiscal\s+years?)\b", query_lower):
            time_horizon = '2years'
        elif re.search(r"\b(?:last|latest|most recent|previous|past|prior)\s+(?:three|3)\s+(?:financial\s+years?|years?|fiscal\s+years?)\b", query_lower):
            time_horizon = '3years'
        elif re.search(r"\b(?:last|latest|most recent|previous|past|prior)\s+(?:five|5)\s+(?:financial\s+years?|years?|fiscal\s+years?)\b", query_lower):
            time_horizon = '5years'
        elif any(word in query_lower for word in ['latest', 'most recent', 'recent']):
            time_horizon = 'latest'
        elif 'next 12 months' in query_lower or 'next year' in query_lower or 'coming year' in query_lower or 'coming 12 months' in query_lower or 'following year' in query_lower:
            time_horizon = 'next_year'
        elif 'next cycle' in query_lower or 'coming period' in query_lower or 'coming cycle' in query_lower or 'near term' in query_lower or 'near-term' in query_lower:
            time_horizon = 'future'
        elif 'medium term' in query_lower or 'medium-term' in query_lower:
            time_horizon = 'medium_term'
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
            (r'last\s+four\s+quarters', 'last four quarters'),
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
        get_peer = False
        peer_phrases = [
            'peer', 'peers', 'competitor', 'competitors',
            'benchmark', 'benchmarking', 'comparable company', 'comparable companies',
            'compare to peers', 'compare with peers', 'compare against peers',
            'vs peers', 'versus peers'
        ]
        for phrase in peer_phrases:
            if phrase in query_lower:
                get_peer = True
                break
        
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
    seen_symbols = set()
    seen_scrip_codes = set()
    company_index = 1

    for company_info in extracted_companies:
        if company_info["matched"]:
            symbol = company_info["security_id"]
            scrip_code = company_info["security_code"]
            if symbol in seen_symbols or scrip_code in seen_scrip_codes:
                continue
            seen_symbols.add(symbol)
            seen_scrip_codes.add(scrip_code)
            target_companies[str(company_index)] = {
                "company": company_info["issuer_name"],
                "symbol": symbol,
                "scrip_code": scrip_code,
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
