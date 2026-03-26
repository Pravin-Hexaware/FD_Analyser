const API_BASE_URL = "http://localhost:8001/api";

export interface CompanySuggestion {
  id: string;
  name: string;
  symbol: string;
  scripcode: string;  // Add scripcode to interface
  sector: string;
}

export interface CompanyData {
  id: string;
  name: string;
  symbol: string;
  bseCode: string;
  sector: string;
  industry: string;
  xbrlLink: string;
  financials?: YearlyFinancials[];
}

export interface YearlyFinancials {
  year: string;
  sales: number;
  ebitda: number;
  opm: number;
  pat: number;
  eps: number;
  roce: number;
  de: number;
  cfo: number;
}

class ApiClient {
  constructor(private baseUrl: string = API_BASE_URL) {}

  private async handleResponse(response: Response) {
    if (!response.ok) {
      throw new Error(`API Error: ${response.statusText}`);
    }
    return response.json();
  }

  // Companies endpoints
  async getAllCompanies(): Promise<CompanyData[]> {
    const response = await fetch(`${this.baseUrl}/companies`);
    const data = await this.handleResponse(response);
    return data.companies;
  }

  async searchCompanies(query: string): Promise<CompanySuggestion[]> {
    if (!query.trim()) return [];
    
    try {
      const response = await fetch(
        `${this.baseUrl}/companies/search?q=${encodeURIComponent(query)}`
      );
      const data = await this.handleResponse(response);
      // Backend now returns array directly for auto-suggestions
      return Array.isArray(data) ? data : [];
    } catch (error) {
      console.error("Search error:", error);
      return [];
    }
  }

  async getCompanyDetails(companyId: string): Promise<CompanyData> {
    const response = await fetch(`${this.baseUrl}/companies/${companyId}`);
    return this.handleResponse(response);
  }

  async getCompanyFinancials(
    companyId: string,
    years: number = 5
  ): Promise<YearlyFinancials[]> {
    const response = await fetch(
      `${this.baseUrl}/companies/${companyId}/financials?years=${years}`
    );
    const data = await this.handleResponse(response);
    return data.financials || [];
  }

  async getTrendingCompanies(): Promise<any[]> {
    const response = await fetch(`${this.baseUrl}/companies/trending`);
    const data = await this.handleResponse(response);
    return data.trending || [];
  }
}


export const apiClient = new ApiClient();
