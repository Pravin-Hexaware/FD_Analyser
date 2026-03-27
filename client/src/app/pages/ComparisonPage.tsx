import { useState, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { Plus, X, Search, Trash2 } from "lucide-react";
import { Button } from "../components/ui/button";
import { AppShell } from "../components/AppShell";
import { fetchCompanies, fetchCompanyFinancials, type CompanyInfo } from "../services/api";

const COMPANY_COLORS = ["#4f46e5", "#0d9488", "#7c3aed", "#dc2626", "#ea580c"];

interface FinancialData {
  [key: string]: any;
}

export default function ComparisonPage() {
  const location = useLocation();
  const [selectedCompanies, setSelectedCompanies] = useState<string[]>([]);
  const [backendCompanies, setBackendCompanies] = useState<CompanyInfo[]>([]);
  const [frequency, setFrequency] = useState<"annual" | "quarterly">("annual");
  const [comparisonData, setComparisonData] = useState<Record<string, FinancialData>>({});
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);

  // Load companies from backend on mount
  useEffect(() => {
    loadCompanies();
  }, []);

  const loadCompanies = async () => {
    try {
      const companiesList = await fetchCompanies();
      setBackendCompanies(companiesList);
    } catch (error) {
      console.warn("Failed to load companies:", error);
      setBackendCompanies([]);
    }
  };

  useEffect(() => {
    const stateCompanies = (location.state as any)?.companyIds;
    const sessionCompanies = sessionStorage.getItem("comparisonData");
    if (stateCompanies) {
      setSelectedCompanies(stateCompanies);
    } else if (sessionCompanies) {
      const parsed = JSON.parse(sessionCompanies);
      setSelectedCompanies(parsed);
      sessionStorage.removeItem("comparisonData");
    }
  }, [location.state]);

  // Fetch comparison data when companies or frequency changes
  useEffect(() => {
    if (selectedCompanies.length >= 2) {
      loadComparisonData();
    }
  }, [selectedCompanies, frequency]);

  const loadComparisonData = async () => {
    setLoading(true);
    const data: Record<string, FinancialData> = {};
    
    for (const scripCode of selectedCompanies) {
      try {
        const financials = await fetchCompanyFinancials(scripCode, frequency);
        console.log(`Loaded ${frequency} data for ${scripCode}:`, financials);
        data[scripCode] = financials;
      } catch (error) {
        console.error(`Failed to load data for ${scripCode}:`, error);
      }
    }
    
    console.log("Comparison data loaded:", data);
    setComparisonData(data);
    setLoading(false);
  };

  const available = backendCompanies.filter((c) => !selectedCompanies.includes(c.scrip_code));
  const selectedData = selectedCompanies
    .map((code: string) => backendCompanies.find((c) => c.scrip_code === code))
    .filter(Boolean) as CompanyInfo[];

  // Filter companies based on search query and sector
  const selectedSectors = [...new Set(selectedData.map(c => c.sector))];
  
  // Include BOTH selected and available companies in the list, but filter by search and sector
  const allCompanies = backendCompanies;
  
  const filteredCompanies = allCompanies.filter((company) => {
    // If companies already selected, only show companies from same sector
    if (selectedCompanies.length > 0 && selectedSectors.length > 0) {
      if (!selectedSectors.includes(company.sector)) {
        return false;
      }
    }
    
    // Apply search filter
    return (
      company.symbol.toLowerCase().includes(searchQuery.toLowerCase()) ||
      company.company_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      company.sector?.toLowerCase().includes(searchQuery.toLowerCase())
    );
  });

  const handleRemoveCompany = (scripCode: string) => {
    setSelectedCompanies(selectedCompanies.filter((id) => id !== scripCode));
  };

  const handleClearAll = () => {
    setSelectedCompanies([]);
    setSearchQuery("");
    setShowDropdown(false);
  };

  return (
    <AppShell
      breadcrumb={[{ label: "Dashboard", href: "/" }, { label: "Compare Companies" }]}
      title="Compare Companies"
      subtitle="Select 2-5 companies to compare their financial metrics"
    >
      <div className="p-4 space-y-4">
        {/* Enhanced Company Selector */}
        <div className="bg-white rounded-lg border border-gray-100 shadow-sm p-6">
          {/* Header with Counter */}
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-semibold text-gray-900">Select Companies to Compare</h3>
              <p className="text-xs text-gray-500 mt-1">Choose 2-5 companies for detailed comparison</p>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex items-center justify-center size-8 rounded-full bg-indigo-100">
                <span className="text-sm font-semibold text-indigo-600">{selectedCompanies.length}/5</span>
              </div>
              {selectedCompanies.length > 0 && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleClearAll}
                  className="text-xs text-red-600 hover:text-red-700 hover:bg-red-50"
                >
                  <Trash2 className="size-3 mr-1" />
                  Clear
                </Button>
              )}
            </div>
          </div>

          {/* Search Bar */}
          <div className="mb-4 relative">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 size-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search by company name, symbol, or sector..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setShowDropdown(true);
                }}
                onFocus={() => setShowDropdown(true)}
                className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-colors"
              />
              {searchQuery && (
                <button
                  onClick={() => {
                    setSearchQuery("");
                    setShowDropdown(false);
                  }}
                  className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  <X className="size-4" />
                </button>
              )}
            </div>

            {/* Multi-select Dropdown with Sector Filter */}
            {showDropdown && selectedCompanies.length < 5 && (
              <div className="absolute top-full mt-2 w-full bg-white border border-gray-200 rounded-lg shadow-lg z-10">
                {/* Sector Info (if companies already selected) */}
                {selectedData.length > 0 && (
                  <div className="px-4 py-3 bg-blue-50 border-b border-gray-200">
                    <p className="text-xs font-semibold text-gray-700">
                      Showing companies from: <span className="text-blue-600">{selectedSectors[0]}</span>
                    </p>
                  </div>
                )}

                {/* Company List with Simple Toggle */}
                {filteredCompanies.length > 0 ? (
                  <div className="max-h-72 overflow-y-auto">
                    {/* Show Selected Companies First */}
                    {selectedData.map((company) => {
                      return (
                        <div
                          key={`selected-${company.scrip_code}`}
                          className="flex items-center gap-3 px-4 py-3.5 border-b border-gray-200 bg-indigo-50 hover:bg-indigo-100 cursor-pointer transition-all"
                          onClick={() => handleRemoveCompany(company.scrip_code)}
                        >
                          {/* Toggle Indicator */}
                          <div className="flex-shrink-0">
                            <div className="w-6 h-6 rounded-full bg-indigo-600 border-2 border-indigo-600 flex items-center justify-center">
                              <svg className="w-3.5 h-3.5 text-white" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                              </svg>
                            </div>
                          </div>

                          {/* Company Avatar */}
                          <div
                            className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                            style={{ backgroundColor: COMPANY_COLORS[selectedCompanies.indexOf(company.scrip_code) % COMPANY_COLORS.length] }}
                          >
                            {company.symbol.charAt(0)}
                          </div>

                          {/* Company Info */}
                          <div className="flex-1 min-w-0">
                            <div className="font-semibold text-gray-900 text-sm">{company.symbol}</div>
                            <div className="text-xs text-gray-600">{company.company_name.substring(0, 40)}</div>
                          </div>
                        </div>
                      );
                    })}

                    {/* Show Available Companies */}
                    {available.filter(c => 
                      filteredCompanies.find(fc => fc.scrip_code === c.scrip_code)
                    ).map((company, idx) => {
                      return (
                        <div
                          key={company.scrip_code}
                          className="flex items-center gap-3 px-4 py-3.5 border-b border-gray-100 last:border-b-0 hover:bg-gray-50 cursor-pointer transition-all"
                          onClick={() => {
                            if (selectedCompanies.length < 5) {
                              setSelectedCompanies([...selectedCompanies, company.scrip_code]);
                              setSearchQuery(""); // Reset search when company selected
                            }
                          }}
                        >
                          {/* Toggle Indicator */}
                          <div className="flex-shrink-0">
                            <div className="w-6 h-6 rounded-full border-2 border-gray-300 flex items-center justify-center"></div>
                          </div>

                          {/* Company Avatar */}
                          <div
                            className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                            style={{ backgroundColor: COMPANY_COLORS[idx % COMPANY_COLORS.length] }}
                          >
                            {company.symbol.charAt(0)}
                          </div>

                          {/* Company Info */}
                          <div className="flex-1 min-w-0">
                            <div className="font-semibold text-gray-900 text-sm">{company.symbol}</div>
                            <div className="text-xs text-gray-600">{company.company_name.substring(0, 40)}</div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="p-6 text-center text-sm text-gray-500">
                    {searchQuery
                      ? `No companies found matching "${searchQuery}"`
                      : selectedData.length > 0
                      ? `No other companies in ${selectedSectors[0]} sector`
                      : "Start typing to search"}
                  </div>
                )}

                {/* Footer with action */}
                <div className="px-4 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-600">
                    {selectedCompanies.length} selected
                  </span>
                  <button
                    onClick={() => setShowDropdown(false)}
                    className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-100 transition-colors"
                  >
                    Close
                  </button>
                </div>
              </div>
            )}

            {/* Dropdown closed message */}
            {!showDropdown && selectedCompanies.length < 5 && (
              <div className="text-xs text-gray-400 mt-2">
                {available.length > 0
                  ? `${available.length} company/companies available`
                  : "All companies selected"}
              </div>
            )}
          </div>
        </div>
        {selectedCompanies.length >= 2 && (
          <div className="bg-white rounded-lg border border-gray-100 shadow-sm overflow-hidden">
            {/* Frequency Toggle */}
            <div className="flex items-center gap-2 p-4 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-900">Financial Period:</span>
              <div className="flex gap-2 ml-auto">
                <button
                  onClick={() => setFrequency("annual")}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                    frequency === "annual"
                      ? "bg-indigo-600 text-white"
                      : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                  }`}
                >
                  Annual
                </button>
                <button
                  onClick={() => setFrequency("quarterly")}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                    frequency === "quarterly"
                      ? "bg-indigo-600 text-white"
                      : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                  }`}
                >
                  Quarterly
                </button>
              </div>
            </div>

            {/* Comparison Table Data */}
            {loading ? (
              <div className="p-8 text-center text-gray-400">Loading financial data...</div>
            ) : selectedCompanies.length >= 2 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      <th className="text-left px-4 py-3 font-semibold text-gray-900">Metric</th>
                      {selectedCompanies.map((code, idx) => {
                        const company = backendCompanies.find(c => c.scrip_code === code);
                        return (
                          <th key={code} className="text-right px-4 py-3 font-semibold text-gray-900 whitespace-nowrap">
                            <div className="font-bold" style={{ color: COMPANY_COLORS[idx] }}>{company?.symbol}</div>
                            <div className="text-xs font-normal text-gray-500">{company?.company_name}</div>
                          </th>
                        );
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {(() => {
                      // Use selectedCompanies directly instead of selectedData
                      if (selectedCompanies.length === 0) {
                        return null;
                      }
                      
                      // Get first company's data
                      const firstCompanyCode = selectedCompanies[0];
                      const firstCompanyData = comparisonData[firstCompanyCode];
                      
                      if (!firstCompanyData || !firstCompanyData.financials || firstCompanyData.financials.length === 0) {
                        return null;
                      }
                      
                      const firstData = firstCompanyData.financials[0];
                      const allKeys = Object.keys(firstData || {});
                      
                      // Define columns for each frequency based on actual database schema
                      const quarterlyMetrics = [
                        'period', 'sales', 'expenses', 'operating_profit', 'opm_percentage', 'other_income',
                        'cost_of_materials_consumed', 'employee_benefit_expense', 'other_expenses',
                        'interest', 'depreciation', 'profit_before_tax', 'current_tax', 'deferred_tax', 'tax', 'tax_percent', 'net_profit', 'eps_in_rs'
                      ];
                      
                      const annualMetrics = [
                        'period', 'sales', 'expenses', 'operating_profit', 'opm_percentage', 'other_income',
                        'interest', 'depreciation', 'profit_before_tax', 'tax_percent', 'net_profit', 'eps_in_rs',
                        // Balance Sheet
                        'equity_capital', 'reserves', 'trade_payables_current', 'borrowings',
                        'other_liabilities', 'total_liabilities', 'total_equity', 'fixed_assets',
                        'cwip', 'investments', 'total_assets',
                        // Cash Flow
                        'cash_from_operating_activity', 'cash_from_investing_activity', 'cash_from_financing_activity'
                      ];
                      
                      // Select metrics based on frequency
                      const metricsToDisplay = frequency === 'annual' ? annualMetrics : quarterlyMetrics;
                      // Filter to only show metrics that exist in the current data
                      const displayMetrics = metricsToDisplay.filter(key => allKeys.includes(key));
                      
                      // Helper function to format values
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
                      
                      // Helper to convert column name to readable label
                      const getLabel = (key: string) => {
                        return key.replace(/_/g, ' ').replace(/([A-Z])/g, ' $1').trim();
                      };
                      
                      return displayMetrics.map((key) => (
                        <tr key={key} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="px-4 py-3 font-medium text-gray-900 text-left">{getLabel(key)}</td>
                          {selectedCompanies.map((code) => {
                            const responseData = comparisonData[code];
                            const financialsList = responseData?.financials;
                            const data = Array.isArray(financialsList) ? financialsList[0] : financialsList;
                            const value = data?.[key];
                            return (
                              <td key={code} className="text-right px-4 py-3 text-gray-700 font-medium">
                                {formatValue(value, key)}
                              </td>
                            );
                          })}
                        </tr>
                      ));
                    })()}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-8 text-center text-gray-400">Select at least 2 companies to compare</div>
            )}
          </div>
        )}

        {selectedCompanies.length === 0 && (
          <div className="text-center py-16">
            <div className="mb-4">
              <Search className="size-12 text-gray-300 mx-auto" />
            </div>
            <p className="text-gray-500 text-lg font-medium">No companies selected</p>
            <p className="text-gray-400 text-sm mt-2">Use the search bar above to find and add 2-5 companies for comparison</p>
          </div>
        )}

        {selectedCompanies.length === 1 && (
          <div className="text-center py-16">
            <div className="mb-4">
              <Plus className="size-12 text-gray-300 mx-auto" />
            </div>
            <p className="text-gray-500 text-lg font-medium">Select more companies</p>
            <p className="text-gray-400 text-sm mt-2">You need at least 2 companies to start comparing</p>
          </div>
        )}
      </div>
    </AppShell>
  );
}
