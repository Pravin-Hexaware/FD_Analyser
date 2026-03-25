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
  {
    id: "reliance",
    name: "Reliance Industries Ltd",
    symbol: "RELIANCE",
    bseCode: "500325",
    sector: "Energy",
    industry: "Oil and Gas",
    xbrlLink: "https://example.com/xbrl/reliance-2025.xml",
    financials: [
      { year: "2025", sales: 920000, ebitda: 135000, opm: 14.7, pat: 75000, eps: 112.5, roce: 12.8, de: 0.45, cfo: 98000 },
      { year: "2024", sales: 875000, ebitda: 128000, opm: 14.6, pat: 71000, eps: 106.5, roce: 12.5, de: 0.48, cfo: 92000 },
      { year: "2023", sales: 825000, ebitda: 118000, opm: 14.3, pat: 67000, eps: 100.5, roce: 12.1, de: 0.52, cfo: 87000 },
      { year: "2022", sales: 780000, ebitda: 110000, opm: 14.1, pat: 62000, eps: 93.0, roce: 11.8, de: 0.55, cfo: 82000 },
      { year: "2021", sales: 720000, ebitda: 98000, opm: 13.6, pat: 55000, eps: 82.5, roce: 11.2, de: 0.60, cfo: 76000 },
    ]
  },
  {
    id: "tcs",
    name: "Tata Consultancy Services Ltd",
    symbol: "TCS",
    bseCode: "532540",
    sector: "Technology",
    industry: "IT Services",
    xbrlLink: "https://example.com/xbrl/tcs-2025.xml",
    financials: [
      { year: "2025", sales: 245000, ebitda: 73500, opm: 30.0, pat: 56000, eps: 152.0, roce: 48.5, de: 0.05, cfo: 62000 },
      { year: "2024", sales: 232000, ebitda: 69600, opm: 30.0, pat: 53000, eps: 144.0, roce: 47.8, de: 0.06, cfo: 58000 },
      { year: "2023", sales: 218000, ebitda: 65400, opm: 30.0, pat: 49500, eps: 134.6, roce: 46.9, de: 0.06, cfo: 54000 },
      { year: "2022", sales: 205000, ebitda: 61500, opm: 30.0, pat: 46500, eps: 126.4, roce: 46.2, de: 0.07, cfo: 51000 },
      { year: "2021", sales: 191000, ebitda: 57300, opm: 30.0, pat: 43200, eps: 117.6, roce: 45.5, de: 0.08, cfo: 47000 },
    ]
  },
  {
    id: "infosys",
    name: "Infosys Ltd",
    symbol: "INFY",
    bseCode: "500209",
    sector: "Technology",
    industry: "IT Services",
    xbrlLink: "https://example.com/xbrl/infosys-2025.xml",
    financials: [
      { year: "2025", sales: 185000, ebitda: 53650, opm: 29.0, pat: 41000, eps: 98.5, roce: 32.5, de: 0.02, cfo: 45000 },
      { year: "2024", sales: 175000, ebitda: 50750, opm: 29.0, pat: 38500, eps: 92.5, roce: 32.0, de: 0.03, cfo: 42000 },
      { year: "2023", sales: 165000, ebitda: 47850, opm: 29.0, pat: 36000, eps: 86.5, roce: 31.5, de: 0.03, cfo: 39000 },
      { year: "2022", sales: 155000, ebitda: 44950, opm: 29.0, pat: 33500, eps: 80.5, roce: 31.0, de: 0.04, cfo: 36000 },
      { year: "2021", sales: 145000, ebitda: 42050, opm: 29.0, pat: 31000, eps: 74.5, roce: 30.5, de: 0.04, cfo: 33000 },
    ]
  },
  {
    id: "asianpaints",
    name: "Asian Paints Ltd",
    symbol: "ASIANPAINT",
    bseCode: "500820",
    sector: "Consumer Goods",
    industry: "Paints and Coatings",
    xbrlLink: "https://example.com/xbrl/asianpaints-2025.xml",
    financials: [
      { year: "2025", sales: 36500, ebitda: 7300, opm: 20.0, pat: 5100, eps: 53.5, roce: 28.5, de: 0.10, cfo: 5800 },
      { year: "2024", sales: 34200, ebitda: 6840, opm: 20.0, pat: 4800, eps: 50.2, roce: 28.0, de: 0.12, cfo: 5400 },
      { year: "2023", sales: 31800, ebitda: 6360, opm: 20.0, pat: 4450, eps: 46.6, roce: 27.5, de: 0.13, cfo: 5000 },
      { year: "2022", sales: 29500, ebitda: 5900, opm: 20.0, pat: 4100, eps: 43.0, roce: 27.0, de: 0.15, cfo: 4600 },
      { year: "2021", sales: 27000, ebitda: 5400, opm: 20.0, pat: 3750, eps: 39.3, roce: 26.5, de: 0.16, cfo: 4200 },
    ]
  },
  {
    id: "hdfc",
    name: "HDFC Bank Ltd",
    symbol: "HDFCBANK",
    bseCode: "500180",
    sector: "Financial Services",
    industry: "Banking",
    xbrlLink: "https://example.com/xbrl/hdfc-2025.xml",
    financials: [
      { year: "2025", sales: 215000, ebitda: 95000, opm: 44.2, pat: 58000, eps: 78.5, roce: 18.5, de: 6.2, cfo: 65000 },
      { year: "2024", sales: 198000, ebitda: 88000, opm: 44.4, pat: 54000, eps: 73.0, roce: 18.2, de: 6.0, cfo: 60000 },
      { year: "2023", sales: 182000, ebitda: 81000, opm: 44.5, pat: 49500, eps: 67.0, roce: 17.9, de: 5.8, cfo: 55000 },
      { year: "2022", sales: 168000, ebitda: 74500, opm: 44.3, pat: 45500, eps: 61.5, roce: 17.6, de: 5.6, cfo: 51000 },
      { year: "2021", sales: 155000, ebitda: 68500, opm: 44.2, pat: 42000, eps: 56.8, roce: 17.3, de: 5.5, cfo: 47000 },
    ]
  },
  {
    id: "wipro",
    name: "Wipro Ltd",
    symbol: "WIPRO",
    bseCode: "507685",
    sector: "Technology",
    industry: "IT Services",
    xbrlLink: "https://example.com/xbrl/wipro-2025.xml",
    financials: [
      { year: "2025", sales: 102000, ebitda: 18360, opm: 18.0, pat: 12750, eps: 25.5, roce: 22.5, de: 0.08, cfo: 14000 },
      { year: "2024", sales: 98000, ebitda: 17640, opm: 18.0, pat: 12250, eps: 24.5, roce: 22.0, de: 0.09, cfo: 13500 },
      { year: "2023", sales: 94000, ebitda: 16920, opm: 18.0, pat: 11750, eps: 23.5, roce: 21.5, de: 0.10, cfo: 13000 },
      { year: "2022", sales: 90000, ebitda: 16200, opm: 18.0, pat: 11250, eps: 22.5, roce: 21.0, de: 0.11, cfo: 12500 },
      { year: "2021", sales: 86000, ebitda: 15480, opm: 18.0, pat: 10750, eps: 21.5, roce: 20.5, de: 0.12, cfo: 12000 },
    ]
  },
];

export const trendingCompanies = [
  { id: "reliance", name: "Reliance", symbol: "RELIANCE", change: "+2.5%" },
  { id: "tcs", name: "TCS", symbol: "TCS", change: "+1.8%" },
  { id: "hdfc", name: "HDFC Bank", symbol: "HDFCBANK", change: "-0.5%" },
  { id: "infosys", name: "Infosys", symbol: "INFY", change: "+3.2%" },
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
