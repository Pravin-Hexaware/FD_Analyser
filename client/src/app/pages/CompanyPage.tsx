import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  MessageSquare, Building2
} from "lucide-react";
import { Button } from "../components/ui/button";
import { AppShell } from "../components/AppShell";
import { fetchCompanyByCode, fetchCompanyFinancials, type CompanyInfo } from "../services/api";

function GitCompareIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" />
      <path d="M13 6h3a2 2 0 0 1 2 2v7" /><path d="M11 18H8a2 2 0 0 1-2-2V9" />
      <polyline points="15 9 18 6 21 9" /><polyline points="9 15 6 18 3 15" />
    </svg>
  );
}

const SECTOR_COLORS: Record<string, string> = {
  "Energy": "bg-orange-100 text-orange-700 border-orange-200",
  "Technology": "bg-blue-100 text-blue-700 border-blue-200",
  "Consumer Goods": "bg-green-100 text-green-700 border-green-200",
  "Financial Services": "bg-purple-100 text-purple-700 border-purple-200",
};

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [company, setCompany] = useState<CompanyInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [frequency, setFrequency] = useState<"annual" | "quarterly">("annual");
  const [financialData, setFinancialData] = useState<any>(null);
  const [financialLoading, setFinancialLoading] = useState(false);

  useEffect(() => {
    const loadCompany = async () => {
      try {
        setLoading(true);
        if (!id) throw new Error("No company ID provided");
        // Use the ID as scrip_code
        const companyData = await fetchCompanyByCode(id.toLowerCase());
        setCompany(companyData);
        
        // Load financial data
        loadFinancialData(id.toLowerCase(), "annual");
        setError(null);
      } catch (err) {
        console.error("Failed to load company:", err);
        setError(err instanceof Error ? err.message : "Failed to load company");
        setCompany(null);
      } finally {
        setLoading(false);
      }
    };

    loadCompany();
  }, [id]);

  const loadFinancialData = async (scripCode: string, freq: "annual" | "quarterly") => {
    try {
      setFinancialLoading(true);
      const data = await fetchCompanyFinancials(scripCode, freq);
      setFinancialData(data);
      setFrequency(freq);
    } catch (err) {
      console.error("Failed to load financial data:", err);
      setFinancialData(null);
    } finally {
      setFinancialLoading(false);
    }
  };

  if (loading) {
    return (
      <AppShell title="Loading...">
        <div className="flex items-center justify-center h-64">
          <div className="text-gray-400">Loading company data...</div>
        </div>
      </AppShell>
    );
  }

  if (!company || error) {
    return (
      <AppShell title="Company Not Found">
        <div className="flex items-center justify-center h-64">
          <div className="text-center">
            <div className="text-gray-400 text-lg mb-3">{error || "Company not found"}</div>
            <Button onClick={() => navigate("/")} className="bg-indigo-600 hover:bg-indigo-700 text-white">
              Go Home
            </Button>
          </div>
        </div>
      </AppShell>
    );
  }

  const sectorClass = SECTOR_COLORS[company.sector || ""] || "bg-gray-100 text-gray-700 border-gray-200";

  // Helper function to format financial values
  const formatValue = (value: any, key: string) => {
    if (value === undefined || value === null || value === 0) return "-";
    
    if (typeof value === 'number') {
      // Percentage columns - identified by explicit keyword
      if (key.includes('percentage') || key.includes('percent')) {
        return `${value.toFixed(2)}%`;
      }
      
      // EPS - show in Rupees (per share)
      if (key.includes('eps')) {
        return `₹${value.toFixed(2)}`;
      }
      
      // Currency columns in Crores
      // P&L columns
      if (key.includes('sales') || key.includes('operating_profit') || key.includes('other_income') || 
          key.includes('cost_of_materials') || key.includes('employee_benefit') || key.includes('other_expenses') || 
          key.includes('interest') || key.includes('depreciation') || key.includes('profit_before_tax') || 
          key.includes('current_tax') || key.includes('deferred_tax') || key.includes('net_profit') || 
          // Balance sheet columns
          key.includes('equity_capital') || key.includes('reserves') || key.includes('trade_payables') || 
          key.includes('borrowing') || key.includes('other_liabilities') || key.includes('total_liabilities') || 
          key.includes('total_equity') || key.includes('fixed_assets') || key.includes('cwip') || 
          key.includes('investment') || key.includes('total_assets') ||
          // Cash flow columns
          key.includes('cash_from')) {
        return `₹${(value / 10).toLocaleString(undefined, { maximumFractionDigits: 0 })} Cr`;
      }
      
      // Expenses and similar columns
      if (key.includes('expense') || key.includes('tax')) {
        return `₹${(value / 10).toLocaleString(undefined, { maximumFractionDigits: 0 })} Cr`;
      }
      
      // Default: return number with 2 decimal places
      return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    
    return String(value);
  };

  // Define columns to exclude from display (metadata)
  const metadataColumns = ['id', 'scrip_code', 'xbrl_link', 'company_name', 'company_symbol', 'currency', 'level_of_rounding', 'reporting_type', 'nature_of_report', 'created_at'];
  
  // Get all columns from the financial data
  const latestFinancial = financialData?.financials?.[0];
  const allColumns = latestFinancial ? Object.keys(latestFinancial).filter(key => !metadataColumns.includes(key)) : [];
  
  // Helper to convert column name to readable label
  const getLabel = (key: string) => {
    return key.replace(/_/g, ' ').replace(/([A-Z])/g, ' $1').trim().split(' ').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
  };

  return (
    <AppShell
      breadcrumb={[
        { label: "Dashboard", href: "/" },
        { label: company.sector || "Company", href: "/" },
        { label: company.symbol },
      ]}
      actions={
        <>
          <Button variant="outline" size="sm" onClick={() => navigate("/compare")} className="text-xs">
            <GitCompareIcon className="size-3.5 mr-1.5" />
            Compare
          </Button>
          <Button variant="outline" size="sm" onClick={() => navigate("/chat")} className="text-xs">
            <MessageSquare className="size-3.5 mr-1.5" />
            Ask AI
          </Button>
        </>
      }
    >
      <div className="p-6">
        {/* Company Header */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 mb-6">
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-4">
              <div className="size-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center shadow-md shadow-indigo-200 flex-shrink-0">
                <span className="text-white font-bold text-lg">{company?.symbol?.charAt(0) || "?"}</span>
              </div>
              <div>
                <h1 className="text-xl font-semibold text-gray-900 mb-1">{company.symbol}</h1>
                <p className="text-sm text-gray-600 mb-3">{company.company_name}</p>
                <div className="flex items-center gap-3 flex-wrap">
                  <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${sectorClass}`}>
                    <Building2 className="size-3" />
                    {company.sector || "N/A"}
                  </div>
                  {company.industry && (
                    <div className="text-xs text-gray-500 bg-gray-50 px-2.5 py-1 rounded-full border border-gray-100">
                      {company.industry}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Company Information */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 mb-6">
          <h3 className="font-semibold text-gray-900 text-sm mb-4">Company Information</h3>
          <div className="grid md:grid-cols-2 gap-6">
            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-400 uppercase tracking-wide">Symbol</label>
                <p className="text-lg font-semibold text-gray-900">{company.symbol}</p>
              </div>
              <div>
                <label className="text-xs text-gray-400 uppercase tracking-wide">Scrip Code</label>
                <p className="text-lg font-semibold text-gray-900">{company.scrip_code}</p>
              </div>
            </div>
            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-400 uppercase tracking-wide">Sector</label>
                <p className="text-lg font-semibold text-gray-900">{company.sector || "N/A"}</p>
              </div>
              <div>
                <label className="text-xs text-gray-400 uppercase tracking-wide">Industry</label>
                <p className="text-lg font-semibold text-gray-900">{company.industry || "N/A"}</p>
              </div>
            </div>
          </div>
        </div>

        {/* Financial Data Section */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          {/* Frequency Toggle */}
          <div className="flex items-center gap-2 p-6 border-b border-gray-100">
            <h3 className="font-semibold text-gray-900">Financial Data</h3>
            <div className="flex gap-2 ml-auto">
              <button
                onClick={() => loadFinancialData(id!.toLowerCase(), 'annual')}
                className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                  frequency === 'annual'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                Annual
              </button>
              <button
                onClick={() => loadFinancialData(id!.toLowerCase(), 'quarterly')}
                className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                  frequency === 'quarterly'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                Quarterly
              </button>
            </div>
          </div>

          {/* Financial Metrics */}
          {financialLoading ? (
            <div className="p-8 text-center text-gray-400">Loading financial data...</div>
          ) : latestFinancial ? (
            <div className="p-6">
              {/* Period Info */}
              <div className="mb-6 pb-6 border-b border-gray-100">
                <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Period</p>
                <p className="text-lg font-semibold text-gray-900">{latestFinancial.period}</p>
              </div>

              {/* All Metrics in Table Format */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <tbody>
                    {allColumns.map((key) => (
                      <tr key={key} className="border-b border-gray-100 hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-900">{getLabel(key)}</td>
                        <td className="text-right px-4 py-3 text-gray-700 font-medium">
                          {formatValue(latestFinancial[key], key)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Additional Info */}
              <div className="mt-6 pt-6 border-t border-gray-100">
                <p className="text-xs text-gray-400">
                  Last Updated: {new Date(latestFinancial.created_at).toLocaleDateString('en-IN', { 
                    year: 'numeric', 
                    month: 'long', 
                    day: 'numeric' 
                  })}
                </p>
              </div>
            </div>
          ) : (
            <div className="p-8 text-center text-gray-400">No financial data available</div>
          )}
        </div>
      </div>
    </AppShell>
  );
}