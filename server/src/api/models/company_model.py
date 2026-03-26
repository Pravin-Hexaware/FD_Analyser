from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

@dataclass
class YearlyFinancials:
    """Financial data for a specific year"""
    year: str
    sales: float
    ebitda: float
    opm: float
    pat: float
    eps: float
    roce: float
    de: float
    cfo: float

@dataclass
class Company:
    """Company model"""
    id: str
    name: str
    symbol: str
    bse_code: str
    sector: str
    industry: str
    xbrl_link: str
    financials: List[YearlyFinancials] = None

    def __post_init__(self):
        if self.financials is None:
            self.financials = []

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "symbol": self.symbol,
            "bseCode": self.bse_code,
            "sector": self.sector,
            "industry": self.industry,
            "xbrlLink": self.xbrl_link,
            "financials": [
                {
                    "year": f.year,
                    "sales": f.sales,
                    "ebitda": f.ebitda,
                    "opm": f.opm,
                    "pat": f.pat,
                    "eps": f.eps,
                    "roce": f.roce,
                    "de": f.de,
                    "cfo": f.cfo,
                }
                for f in self.financials
            ]
        }
