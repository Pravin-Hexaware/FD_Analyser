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
  baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

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
    return data.companies || [];
    // Backend returns array directly, not wrapped in object
    return Array.isArray(data) ? data : [];
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

  async getCompanyDetails(companyId: string): Promise<{ success: boolean; company?: CompanyData }> {
    try {
      const response = await fetch(`${this.baseUrl}/companies/${companyId}`);
      if (!response.ok) {
        console.warn(`Company ${companyId} not found (${response.status})`);
        return { success: false, company: undefined };
      }
      const data = await response.json();
      return { success: true, company: data.company };
    } catch (error) {
      console.error("Error fetching company details:", error);
      return { success: false, company: undefined };
    }
  }

  async resolveCompany(query: string): Promise<CompanyData[]> {
    try {
      const response = await fetch(`${this.baseUrl}/companies/resolve?query=${encodeURIComponent(query)}`);
      if (!response.ok) {
        console.warn(`Failed to resolve company: ${query}`);
        return [];
      }
      const data = await response.json();
      return Array.isArray(data.companies) ? data.companies : [];
    } catch (error) {
      console.error("Error resolving company:", error);
      return [];
    }
  }

  async getCompanyFinancials(
    companyId: string,
    years: number = 5
  ): Promise<{ success: boolean; financials: YearlyFinancials[] }> {
    const response = await fetch(
      `${this.baseUrl}/companies/${companyId}/financials?years=${years}`
    );
    return this.handleResponse(response);
  }

  async getTrendingCompanies(): Promise<any[]> {
    const response = await fetch(`${this.baseUrl}/companies/trending`);
    const data = await this.handleResponse(response);
    return data.trending || [];
  }
}


export const apiClient = new ApiClient();
