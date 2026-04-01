// API service for backend communication
import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // Increased to 2 minutes for long LLM processing
  headers: {
    'Content-Type': 'application/json',
  },
});

export interface LLMQueryRequest {
  query: string;
  conversation_id?: number;
}

export interface LLMQueryResponse {
  chat_id: string;
  answer: string;
}

export interface ChatHistoryItem {
  chat_id: string;
  title: string;
  created_at: string;
  last_message?: string;
}

export interface ConversationMessage {
  id: number;
  sequence_number: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ConversationDetail {
  chat_id: string;
  title: string;
  created_at: string;
  messages: ConversationMessage[];
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
export async function sendLLMQuery(query: string, conversationId?: number): Promise<LLMQueryResponse> {
  try {
    const payload: LLMQueryRequest = { query };
    if (conversationId !== undefined) {
      payload.conversation_id = conversationId;
    }

    const response = await apiClient.post<LLMQueryResponse>(
      '/llm/target_companies',
      payload
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
export async function fetchChat(chatId: string): Promise<ConversationDetail> {
  try {
    const response = await apiClient.get<ConversationDetail>(`/llm/chat-history/${chatId}`);
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

    // Backend may return either plain array or an envelope with companies key.
    if (Array.isArray(response.data)) {
      return response.data;
    }

    if (response.data && Array.isArray((response.data as any).companies)) {
      return (response.data as any).companies;
    }

    return [];
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
    let endpoint = `/companies/${scripCode}/financials`;

    // Prefer explicit annual/quarterly routes for determinism and fewer 404s
    if (frequency === 'annual') {
      endpoint = `/companies/${scripCode}/annual`;
    } else if (frequency === 'quarterly') {
      endpoint = `/companies/${scripCode}/quarterly`;
    }

    const response = await apiClient.get(endpoint, {
      params: frequency === 'annual' || frequency === 'quarterly' ? {} : { frequency },
    });

    const data = response.data;

    // Normalize shape for ComparisonPage (expects .financials array)
    if (Array.isArray(data.financials)) {
      return data;
    }

    if (data.annual) {
      return {
        ...data,
        financials: Array.isArray(data.annual) ? data.annual : [data.annual],
      };
    }

    if (data.quarterly) {
      return {
        ...data,
        financials: Array.isArray(data.quarterly) ? data.quarterly : [data.quarterly],
      };
    }

    // Fallback to deprecated route format if data already is a list or object
    if (Array.isArray(data)) {
      return { financials: data };
    }

    return data;
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
