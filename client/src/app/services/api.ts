// API service for backend communication
import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

export interface LLMQueryRequest {
  query: string;
}

export interface LLMQueryResponse {
  chat_id: string;
  answer: string;
}

export interface ChatHistoryItem {
  chat_id: string;
  user_query: string;
  response: string;
  created_at: string;
  title: string;
}

export interface CompanyInfo {
  id: string;
  scrip_code: string;
  company_name: string;
  symbol: string;
  sector?: string;
  industry?: string;
}

export interface CompanyFinancial {
  scrip_code: string;
  company_name: string;
  symbol: string;
  period: string;
  sales?: number;
  operating_profit?: number;
  opm?: number;
  pat?: number;
  eps?: number;
  equity?: number;
  total_assets?: number;
  borrowings?: number;
  cfo?: number;
  date?: string;
}

export interface CompanyComparisonData {
  companies: CompanyFinancial[];
  frequency: string;
  count: number;
}

/**
 * Send a chat query to the backend LLM endpoint
 * @param query - The user's query
 * @returns The response with chat_id and answer
 */
export async function sendLLMQuery(query: string): Promise<LLMQueryResponse> {
  try {
    const response = await apiClient.post<LLMQueryResponse>(
      '/llm/target_companies',
      { query } as LLMQueryRequest
    );
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || error.message;
      throw new Error(`Backend error: ${message}`);
    }
    throw error;
  }
}

/**
 * Fetch chat history from backend
 * @returns List of chat history items
 */
export async function fetchChatHistory(): Promise<ChatHistoryItem[]> {
  try {
    const response = await apiClient.get<ChatHistoryItem[]>('/llm/chat-history');
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || error.message;
      throw new Error(`Backend error: ${message}`);
    }
    throw error;
  }
}

/**
 * Fetch a specific chat by ID
 * @param chatId - The chat ID to fetch
 * @returns The chat details
 */
export async function fetchChat(chatId: string): Promise<ChatHistoryItem> {
  try {
    const response = await apiClient.get<ChatHistoryItem>(`/llm/chat-history/${chatId}`);
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || error.message;
      throw new Error(`Backend error: ${message}`);
    }
    throw error;
  }
}

/**
 * Fetch all companies from backend
 * @returns List of all companies
 */
export async function fetchCompanies(): Promise<CompanyInfo[]> {
  try {
    const response = await apiClient.get<CompanyInfo[]>('/companies');
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || error.message;
      throw new Error(`Backend error: ${message}`);
    }
    throw error;
  }
}

/**
 * Fetch a single company by scrip code
 * @param scripCode - The scrip code of the company
 * @returns Company info
 */
export async function fetchCompanyByCode(scripCode: string): Promise<CompanyInfo> {
  try {
    const response = await apiClient.get<CompanyInfo>(`/companies/${scripCode}`);
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || error.message;
      throw new Error(`Backend error: ${message}`);
    }
    throw error;
  }
}

/**
 * Fetch financial data for a company
 * @param scripCode - The scrip code of the company
 * @param frequency - "annual" or "quarterly"
 * @returns Company financial data
 */
export async function fetchCompanyFinancials(
  scripCode: string,
  frequency: string = 'annual'
): Promise<any> {
  try {
    const response = await apiClient.get(
      `/companies/${scripCode}/financials`,
      { params: { frequency } }
    );
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || error.message;
      throw new Error(`Backend error: ${message}`);
    }
    throw error;
  }
}

/**
 * Compare multiple companies
 * @param scripCodes - Array of scrip codes to compare
 * @param frequency - "annual" or "quarterly"
 * @returns Comparison data for all companies
 */
export async function compareCompanies(
  scripCodes: string[],
  frequency: string = 'annual'
): Promise<CompanyComparisonData> {
  try {
    const response = await apiClient.post<CompanyComparisonData>(
      '/companies/compare',
      { scrip_codes: scripCodes, frequency }
    );
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || error.message;
      throw new Error(`Backend error: ${message}`);
    }
    throw error;
  }
}

export default apiClient;
