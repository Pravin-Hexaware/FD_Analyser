import { useState, useEffect, useRef } from "react";
import { Plus, X, Search, Trash2 } from "lucide-react";
import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { Button } from "../components/ui/button";
import { AppShell } from "../components/AppShell";
import { fetchCompanies, fetchCompanyFinancials, compareExtractionData, type CompanyInfo } from "../services/api";

const COMPANY_COLORS = ["#4f46e5", "#0d9488", "#7c3aed", "#dc2626", "#ea580c"];

interface FinancialData {
  [key: string]: any;
}

export default function ComparisonPage() {
  const [selectedCompanies, setSelectedCompanies] = useState<string[]>([]);
  const [backendCompanies, setBackendCompanies] = useState<CompanyInfo[]>([]);
  const [frequency, setFrequency] = useState<"annual" | "quarterly">("annual");
  const [selectedPeriod, setSelectedPeriod] = useState<string>("latest year");
  const [comparisonData, setComparisonData] = useState<Record<string, FinancialData>>({});
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedSector, setSelectedSector] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0, width: 0 });

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

  // Handle clicks outside dropdown to close it
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node) && 
          searchInputRef.current && !searchInputRef.current.contains(event.target as Node)) {
        setShowDropdown(false);
      }
    };

    if (showDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showDropdown]);

  // Update dropdown position whenever it should show
  useEffect(() => {
    const updatePosition = () => {
      if (searchInputRef.current && showDropdown) {
        const rect = searchInputRef.current.getBoundingClientRect();
        setDropdownPosition({
          top: rect.bottom + 8,
          left: rect.left,
          width: rect.width
        });
      }
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);

    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [showDropdown]);

  // Fetch comparison data when companies or frequency changes
  useEffect(() => {
    if (selectedCompanies.length >= 2) {
      loadComparisonData();
    }
  }, [selectedCompanies, frequency, selectedPeriod]);

  const loadComparisonData = async () => {
    setLoading(true);

    try {
      const response = await compareExtractionData(selectedCompanies, frequency, selectedPeriod);
      if (response?.companies && Object.keys(response.companies).length > 0) {
        setComparisonData(response.companies);
      } else {
        const fallbackData: Record<string, FinancialData> = {};
        for (const scripCode of selectedCompanies) {
          try {
            const financials = await fetchCompanyFinancials(scripCode, frequency);
            fallbackData[scripCode] = financials;
          } catch (error) {
            console.error(`Failed to load fallback data for ${scripCode}:`, error);
          }
        }
        setComparisonData(fallbackData);
      }
    } catch (error) {
      console.error("Comparison extraction failed:", error);
      const fallbackData: Record<string, FinancialData> = {};
      for (const scripCode of selectedCompanies) {
        try {
          const financials = await fetchCompanyFinancials(scripCode, frequency);
          fallbackData[scripCode] = financials;
        } catch (fetchError) {
          console.error(`Failed to load fallback data for ${scripCode}:`, fetchError);
        }
      }
      setComparisonData(fallbackData);
    } finally {
      setLoading(false);
    }
  };

  const available = backendCompanies.filter((c) => !selectedCompanies.includes(c.scrip_code));
  const selectedData = selectedCompanies
    .map((code: string) => backendCompanies.find((c) => c.scrip_code === code))
    .filter(Boolean) as CompanyInfo[];

  const getRecentFiscalYears = () => {
    const now = new Date();
    const endYear = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
    return Array.from({ length: 5 }, (_, index) => {
      const year = endYear - index;
      const startYear = year - 1;
      return {
        label: `FY${startYear}-${year}`,
        value: `FY${startYear}-${year}`,
      };
    });
  };

  // Filter companies based on search query and (optional) selected sector
  const selectedSectors = Array.from(new Set(selectedData.map((c) => c.sector)));

  // All companies helper
  const allCompanies = backendCompanies || [];

  // Unique sector list for suggestions
  const sectorList = Array.from(new Set(allCompanies.map((c) => (c.sector || "").trim()))).filter(Boolean);

  // When a sector is selected, only show companies from that sector in the dropdown
  const companiesForSelectedSector = selectedSector
    ? allCompanies.filter((c) => (c.sector || "").toLowerCase() === selectedSector.toLowerCase())
    : allCompanies;

  const filteredCompanies = companiesForSelectedSector.filter((company) => {
    // If user has already selected companies, prefer showing companies from same sector(s)
    if (selectedCompanies.length > 0 && selectedSectors.length > 0 && !selectedSector) {
      if (!selectedSectors.includes(company.sector)) return false;
    }

    // Apply search filter (matches symbol, name or sector)
    const q = searchQuery.trim().toLowerCase();
    if (!q) return true;
    return (
      (company.symbol || "").toLowerCase().includes(q) ||
      (company.company_name || "").toLowerCase().includes(q) ||
      (company.sector || "").toLowerCase().includes(q)
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

  const normalizeToCrores = (value: number, levelOfRounding?: string): number => {
    if (typeof value !== "number" || Number.isNaN(value) || !Number.isFinite(value)) {
      return value;
    }

    const unit = String(levelOfRounding || "").trim().toLowerCase();
    if (unit.includes("crore") || unit.includes("cr")) {
      return value;
    }
    if (unit.includes("lakh") || unit.includes("lac")) {
      return value / 10;
    }
    if (unit.includes("million") || unit.includes("mn")) {
      return value / 10;
    }
    if (unit.includes("billion") || unit.includes("bn")) {
      return value * 100;
    }
    if (unit.includes("thousand") || unit.includes("k")) {
      return value / 100000;
    }

    return value;
  };

  const formatFinancialValue = (value: any, key: string, levelOfRounding?: string) => {
    if (value === undefined || value === null) {
      return "-";
    }

    if (typeof value === "number") {
      const label = key.toLowerCase();
      if (label.includes("percentage") || label.includes("percent")) {
        return `${value.toFixed(2)}%`;
      }
      if (label.includes("eps") || label.includes("earnings")) {
        return `₹${value.toFixed(2)}`;
      }

      const crores = normalizeToCrores(value, levelOfRounding);
      return `₹${crores.toLocaleString("en-IN", { maximumFractionDigits: 2 })} Cr`;
    }

    return String(value);
  };

  const getLabel = (key: string) => {
    return key
      .replace(/_/g, " ")
      .replace(/([A-Z])/g, " $1")
      .trim()
      .replace(/\s+/g, " ");
  };

  const metricGroups = [
    {
      label: "Profit & Loss",
      color: "#eef2ff",
      metrics: [
        "period",
        "sales",
        "expenses",
        "operating_profit",
        "opm_percentage",
        "other_income",
        "cost_of_materials_consumed",
        "employee_benefit_expense",
        "other_expenses",
        "interest",
        "depreciation",
        "profit_before_tax",
        "current_tax",
        "deferred_tax",
        "tax",
        "tax_percent",
        "net_profit",
        "eps_in_rs",
      ],
    },
    {
      label: "Balance Sheet",
      color: "#ecfdf5",
      metrics: [
        "equity_capital",
        "reserves",
        "trade_payables_current",
        "borrowings",
        "other_liabilities",
        "total_liabilities",
        "total_equity",
        "fixed_assets",
        "cwip",
        "investments",
        "total_assets",
      ],
    },
    {
      label: "Cash Flow",
      color: "#f0f9ff",
      metrics: [
        "cash_from_operating_activity",
        "cash_from_investing_activity",
        "cash_from_financing_activity",
      ],
    },
  ];

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
          <div className="mb-4">
            <div className="flex items-start justify-between gap-4">
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

            {selectedCompanies.length > 0 && (
              <div className="mt-4 border-t border-gray-100 pt-4">
                <div className="text-xs font-semibold text-gray-700 mb-2">Selected companies</div>
                <div className="flex flex-wrap gap-2">
                  {selectedData.map((company) => (
                    <div
                      key={company.scrip_code}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium transition-all"
                      style={{
                        borderColor: COMPANY_COLORS[selectedCompanies.indexOf(company.scrip_code) % COMPANY_COLORS.length] + "40",
                        backgroundColor: COMPANY_COLORS[selectedCompanies.indexOf(company.scrip_code) % COMPANY_COLORS.length] + "10",
                        color: COMPANY_COLORS[selectedCompanies.indexOf(company.scrip_code) % COMPANY_COLORS.length]
                      }}
                    >
                      <span className="font-semibold">{company.symbol}</span>
                      <button
                        onClick={() => handleRemoveCompany(company.scrip_code)}
                        className="flex-shrink-0 ml-1 p-0.5 hover:bg-red-100 hover:text-red-600 text-gray-400 rounded-full transition-colors"
                        title="Remove company"
                      >
                        <X className="size-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Search Bar */}
          <div className="mb-4 relative">
            <div className="relative">
              <div className="flex items-center gap-2">
                <Search className="size-4 text-gray-400" />

                {selectedSector ? (
                  <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-50 border border-indigo-100">
                    <span className="text-xs font-medium text-indigo-700">{selectedSector}</span>
                    <button
                      onClick={() => {
                        setSelectedSector(null);
                        setSearchQuery("");
                        setShowDropdown(false);
                      }}
                      className="text-gray-400 hover:text-gray-600"
                      aria-label="Clear sector"
                    >
                      <X className="size-4" />
                    </button>
                  </div>
                ) : null}

                <input
                  ref={searchInputRef}
                  type="text"
                  placeholder={selectedSector ? "Filter companies in selected sector..." : "Search by company name, symbol, or sector..."}
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setShowDropdown(true);
                  }}
                  onFocus={() => setShowDropdown(true)}
                  className="w-full pl-2 pr-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-colors"
                />

                {searchQuery && (
                  <button
                    onClick={() => {
                      setSearchQuery("");
                      setShowDropdown(false);
                    }}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    <X className="size-4" />
                  </button>
                )}
              </div>
            </div>

            {/* Multi-select Dropdown with Sector Filter */}
            {showDropdown && selectedCompanies.length < 5 && (
                <div 
                  ref={dropdownRef}
                  className="fixed bg-white border border-gray-200 rounded-xl shadow-2xl z-[10000]"
                  style={{
                    top: `${dropdownPosition.top}px`,
                    left: `${dropdownPosition.left}px`,
                    width: `${dropdownPosition.width}px`,
                    maxHeight: '400px',
                    overflowY: 'auto'
                  }}
                >
                {/* If no sector selected, show sector suggestions */}
                {!selectedSector ? (
                  <>
                    <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
                      <p className="text-xs font-semibold text-gray-700">Select a sector</p>
                    </div>
                    <div className="max-h-72 overflow-y-auto">
                      {sectorList
                        .filter((s) => s.toLowerCase().includes(searchQuery.toLowerCase()))
                        .map((sector) => (
                          <div
                            key={sector}
                            className="flex items-center gap-3 px-4 py-3.5 border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-all"
                            onClick={() => {
                              setSelectedSector(sector);
                              setSearchQuery("");
                              setShowDropdown(true);
                            }}
                          >
                            <div className="flex-1 min-w-0">
                              <div className="font-semibold text-gray-900 text-sm">{sector}</div>
                            </div>
                          </div>
                        ))}
                      {sectorList.filter((s) => s.toLowerCase().includes(searchQuery.toLowerCase())).length === 0 && (
                        <div className="p-6 text-center text-sm text-gray-500">No sectors found</div>
                      )}
                    </div>
                  </>
                ) : (
                  // Sector selected: show companies for that sector
                  <>
                    <div className="px-4 py-3 bg-blue-50 border-b border-gray-200 flex items-center justify-between">
                      <p className="text-xs font-semibold text-gray-700">Showing companies from: <span className="text-blue-600">{selectedSector}</span></p>
                      <button className="text-xs text-gray-500" onClick={() => { setSelectedSector(null); setSearchQuery(""); setShowDropdown(true); }}>Clear</button>
                    </div>

                    <div className="max-h-72 overflow-y-auto">
                      {/* Show selected companies (if any belong to this sector) */}
                      {selectedData.filter(c => (c.sector || "").toLowerCase() === selectedSector.toLowerCase()).map((company) => (
                        <div
                          key={`selected-${company.scrip_code}`}
                          className="flex items-center gap-3 px-4 py-3.5 border-b border-gray-200 bg-indigo-50 hover:bg-indigo-100 cursor-pointer transition-all"
                          onClick={() => handleRemoveCompany(company.scrip_code)}
                        >
                          <div className="flex-1 min-w-0">
                            <div className="font-semibold text-gray-900 text-sm">{company.symbol}</div>
                            <div className="text-xs text-gray-600">{company.company_name.substring(0, 40)}</div>
                          </div>
                        </div>
                      ))}

                      {/* Show available companies from selected sector */}
                      {available
                        .filter((c) => (c.sector || "").toLowerCase() === selectedSector.toLowerCase())
                        .filter(c => filteredCompanies.find(fc => fc.scrip_code === c.scrip_code))
                        .map((company) => (
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
                            <div className="flex-1 min-w-0">
                              <div className="font-semibold text-gray-900 text-sm">{company.symbol}</div>
                              <div className="text-xs text-gray-600">{company.company_name.substring(0, 40)}</div>
                            </div>
                          </div>
                        ))}

                      {available.filter((c) => (c.sector || "").toLowerCase() === selectedSector.toLowerCase()).length === 0 && (
                        <div className="p-6 text-center text-sm text-gray-500">No companies found in this sector</div>
                      )}
                    </div>
                  </>
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

            {/* Max selection message */}
            {selectedCompanies.length === 5 && (
              <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <p className="text-xs text-amber-700">
                  <span className="font-semibold">Maximum 5 companies selected.</span> Remove a company to add another.
                </p>
              </div>
            )}
          </div>
        </div>
        {selectedCompanies.length >= 2 && (
          <div className="bg-white rounded-lg border border-gray-100 shadow-sm">
            <div className="sticky top-0 z-30 bg-white shadow-sm">
              {/* Frequency Toggle */}
              <div className="flex items-center gap-2 p-4 border-b border-gray-100">
                <span className="text-sm font-semibold text-gray-900">Financial Period:</span>
                <div className="flex gap-2 ml-auto">
                <button
                  onClick={() => {
                    setFrequency("annual");
                    setSelectedPeriod("latest year");
                  }}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                    frequency === "annual"
                      ? "bg-indigo-600 text-white"
                      : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                  }`}
                >
                  Annual
                </button>
                <button
                  onClick={() => {
                    setFrequency("quarterly");
                    setSelectedPeriod("latest quarter");
                  }}
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

            {/* Period Selection Toggle */}
            <div className="flex items-center gap-2 p-4 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-900">Period:</span>
              <div className="flex flex-wrap gap-2 ml-auto">
                {frequency === "quarterly" ? (
                  [
                    { label: "Latest quarter", value: "latest quarter" },
                    { label: "March", value: "march" },
                    { label: "June", value: "june" },
                    { label: "September", value: "september" },
                    { label: "December", value: "december" },
                  ].map((option) => (
                    <button
                      key={option.value}
                      onClick={() => setSelectedPeriod(option.value)}
                      className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                        selectedPeriod === option.value
                          ? "bg-indigo-600 text-white"
                          : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))
                ) : (
                  [{ label: "Latest year", value: "latest year" }, ...getRecentFiscalYears()].map((option) => (
                    <button
                      key={option.value}
                      onClick={() => setSelectedPeriod(option.value)}
                      className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                        selectedPeriod === option.value
                          ? "bg-indigo-600 text-white"
                          : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>

            {/* Comparison Table Data */}
            {loading ? (
              <div className="p-8 text-center text-gray-400">Loading financial data...</div>
            ) : selectedCompanies.length >= 2 ? (
              <Box sx={{ position: 'relative' }}>
                <TableContainer
                  component={Paper}
                  sx={{
                    borderRadius: 3,
                    border: '1px solid',
                    borderColor: 'divider',
                    boxShadow: 1,
                    overflowX: 'auto',
                  }}
                >
                  <Table stickyHeader sx={{ minWidth: 960 }} size="small">
                    <TableHead>
                      <TableRow sx={{ backgroundColor: 'background.default' }}>
                        <TableCell sx={{ fontWeight: 700, fontSize: '0.95rem' }}>Metric</TableCell>
                        {selectedCompanies.map((code, idx) => {
                          const company = backendCompanies.find((c) => c.scrip_code === code);
                          return (
                            <TableCell
                              key={code}
                              align="right"
                              sx={{
                                fontWeight: 700,
                                whiteSpace: 'nowrap',
                                px: 3,
                                py: 2,
                              }}
                            >
                              <Typography
                                variant="subtitle2"
                                sx={{ fontWeight: 700, color: COMPANY_COLORS[idx], lineHeight: 1.1 }}
                              >
                                {company?.symbol}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {company?.company_name}
                              </Typography>
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {(() => {
                        if (selectedCompanies.length === 0) {
                          return null;
                        }

                        const firstCompanyCode = selectedCompanies[0];
                        const firstCompanyData = comparisonData[firstCompanyCode];
                        if (!firstCompanyData?.financials?.length) {
                          return null;
                        }

                        const firstData = firstCompanyData.financials[0];
                        const allKeys = Object.keys(firstData || {});

                        const orderedMetrics = metricGroups.flatMap((group) =>
                          group.metrics.filter((key) => allKeys.includes(key))
                        );

                        return orderedMetrics.map((key) => {
                          const metricValues = selectedCompanies.map((code) => {
                            const responseData = comparisonData[code];
                            const financialsList = responseData?.financials;
                            const data = Array.isArray(financialsList) ? financialsList[0] : financialsList;
                            return data?.[key];
                          });

                          const best = metricValues
                            .map((v, idx) => ({ value: typeof v === 'number' ? v : null, index: idx }))
                            .filter((item) => item.value !== null && item.value !== 0)
                            .reduce((bestSoFar, current) => {
                              if (!bestSoFar) return current;
                              if (key.includes('borrowing') || key.includes('debt') || key.includes('liabilities')) {
                                return (current.value ?? 0) < (bestSoFar.value ?? 0) ? current : bestSoFar;
                              }
                              return (current.value ?? 0) > (bestSoFar.value ?? 0) ? current : bestSoFar;
                            }, null as { value: any; index: number } | null);

                          return (
                            <TableRow key={key}>
                              <TableCell sx={{ px: 3, py: 2, fontWeight: 600, color: 'text.primary' }}>
                                {getLabel(key)}
                              </TableCell>
                              {selectedCompanies.map((code, idx) => {
                                const responseData = comparisonData[code];
                                const financialsList = responseData?.financials;
                                const data = Array.isArray(financialsList) ? financialsList[0] : financialsList;
                                const value = data?.[key];
                                const companyLevelOfRounding = data?.level_of_rounding || '';
                                const isBestValue = best && idx === best.index && value !== 0 && value !== null && value !== undefined;

                                return (
                                  <TableCell
                                    key={code}
                                    align="right"
                                    sx={{
                                      px: 3,
                                      py: 2,
                                      fontWeight: isBestValue ? 700 : 500,
                                      color: isBestValue ? 'success.main' : 'text.secondary',
                                      backgroundColor: isBestValue ? 'success.lighter' : 'inherit',
                                    }}
                                  >
                                    {formatFinancialValue(value, key, companyLevelOfRounding)}
                                  </TableCell>
                                );
                              })}
                            </TableRow>
                          );
                        });
                      })()}
                    </TableBody>
                  </Table>
                </TableContainer>
                <Box sx={{ px: 3, py: 2, backgroundColor: 'background.paper' }}>
                  <Typography variant="caption" color="text.secondary">
                    All monetary values are shown in Indian rupees crores (₹ Cr). Percentages and EPS are shown in standard units.
                  </Typography>
                </Box>
              </Box>
            ) : (
              <div className="p-8 text-center text-gray-400">Select at least 2 companies to compare</div>
            )}
          </div>
        )}

        {selectedCompanies.length === 0 && (
          <div className="text-center py-16">
            <div className="mb-6">
              <Search className="size-12 text-gray-300 mx-auto" />
            </div>
            <p className="text-gray-500 text-lg font-medium mb-6">No companies selected</p>
            
            {/* Add Tile Button */}
            <button
              onClick={() => setShowDropdown(true)}
              className="inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-full border-2 border-dashed border-indigo-300 hover:border-indigo-500 hover:bg-indigo-50 transition-all mb-4"
            >
              <Plus className="size-5 text-indigo-600" />
              <span className="font-semibold text-indigo-600">Add Companies</span>
            </button>
            
            <p className="text-gray-400 text-sm mt-4">Or use the search bar above to find and add 2-5 companies for comparison</p>
          </div>
        )}

        {selectedCompanies.length === 1 && (
          <div className="text-center py-16">
            <div className="mb-6">
              <Plus className="size-12 text-gray-300 mx-auto" />
            </div>
            <p className="text-gray-500 text-lg font-medium mb-6">Select more companies</p>
            
            {/* Add More Tile Button */}
            <button
              onClick={() => setShowDropdown(true)}
              className="inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-full border-2 border-dashed border-indigo-300 hover:border-indigo-500 hover:bg-indigo-50 transition-all mb-4"
            >
              <Plus className="size-5 text-indigo-600" />
              <span className="font-semibold text-indigo-600">Add More Companies</span>
            </button>
            
            <p className="text-gray-400 text-sm mt-4">You need at least 2 companies to start comparing</p>
          </div>
        )}
      </div>
    </AppShell>
  );
}