// Mock financial data for companies
console.log(">>> Loaded companies.ts from:", import.meta.url);
export interface CompanyData {
  id: string;
  name: string;
  symbol: string;
  bseCode: string;
  sector: string;
  industry: string;
  xbrlLink: string;
  financials: YearlyFinancials[];
}

export interface YearlyFinancials {
  year: string;
  sales: number;
  ebitda: number;
  opm: number; // Operating Profit Margin %
  pat: number; // Profit After Tax
  eps: number;
  roce: number; // Return on Capital Employed %
  de: number; // Debt to Equity
  cfo: number; // Cash Flow from Operations
}

export const companies: CompanyData[] = [
];

export const trendingCompanies = [
];

export function getCompanyById(id: string): CompanyData | undefined {
  return companies.find(c => c.id === id);
}

export function getCompanyBySymbol(symbol: string): CompanyData | undefined {
  return companies.find(c => c.symbol.toLowerCase() === symbol.toLowerCase());
}

export function searchCompanies(query: string): CompanyData[] {
  const q = query.toLowerCase();
  return companies.filter(c => 
    c.name.toLowerCase().includes(q) || 
    c.symbol.toLowerCase().includes(q) ||
    c.bseCode.includes(q)
  );
}
