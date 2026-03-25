import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Plus, X, Sparkles, BarChart3, Trophy } from "lucide-react";
import { Button } from "../components/ui/button";
import { companies, getCompanyById } from "../data/companies";
import { ComparisonTable } from "../components/ComparisonTable";
import { generateAIReport } from "../data/chatbot";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { AppShell } from "../components/AppShell";

const COMPANY_COLORS = ["#4f46e5", "#0d9488", "#7c3aed", "#dc2626", "#ea580c"];

const SECTOR_STYLES: Record<string, string> = {
  "Energy": "bg-orange-50 border-orange-200 text-orange-700",
  "Technology": "bg-blue-50 border-blue-200 text-blue-700",
  "Consumer Goods": "bg-green-50 border-green-200 text-green-700",
  "Financial Services": "bg-purple-50 border-purple-200 text-purple-700",
};

export default function ComparisonPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [selectedCompanies, setSelectedCompanies] = useState<string[]>([]);

  useEffect(() => {
    const stateCompanies = (location.state as any)?.companyIds;
    const sessionCompanies = sessionStorage.getItem("comparisonData");
    if (stateCompanies) {
      setSelectedCompanies(stateCompanies);
    } else if (sessionCompanies) {
      setSelectedCompanies(JSON.parse(sessionCompanies));
      sessionStorage.removeItem("comparisonData");
    }
  }, [location.state]);

  const handleAddCompany = (companyId: string) => {
    if (!selectedCompanies.includes(companyId) && selectedCompanies.length < 5) {
      setSelectedCompanies([...selectedCompanies, companyId]);
    }
  };

  const handleRemoveCompany = (companyId: string) => {
    setSelectedCompanies(selectedCompanies.filter((id) => id !== companyId));
  };

  const handleGenerateReport = () => {
    const selectedData = selectedCompanies
      .map((id) => getCompanyById(id))
      .filter(Boolean) as any;
    const report = generateAIReport(selectedCompanies, selectedData);
    navigate(`/report/${report.id}`, { state: { report } });
  };

  const available = companies.filter((c) => !selectedCompanies.includes(c.id));
  const selectedData = selectedCompanies.map((id) => getCompanyById(id)).filter(Boolean) as NonNullable<ReturnType<typeof getCompanyById>>[];

  return (
    <AppShell
      breadcrumb={[{ label: "Dashboard", href: "/" }, { label: "Compare Companies" }]}
      title="Compare Companies"
      subtitle="Select 2–5 companies to compare financials and generate AI analysis"
      actions={
        selectedCompanies.length >= 2 ? (
          <Button
            onClick={handleGenerateReport}
            className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs"
            size="sm"
          >
            <Sparkles className="size-3.5 mr-1.5" />
            Generate AI Report
          </Button>
        ) : undefined
      }
    >
      <div className="p-6 space-y-6">
        {/* Company Selector */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="font-semibold text-gray-900">Selected Companies</h2>
              <p className="text-xs text-gray-400 mt-0.5">{selectedCompanies.length}/5 selected</p>
            </div>
            {available.length > 0 && selectedCompanies.length < 5 && (
              <Select onValueChange={handleAddCompany}>
                <SelectTrigger className="w-56 text-sm h-9 border-gray-200">
                  <div className="flex items-center gap-2">
                    <Plus className="size-3.5 text-gray-400" />
                    <SelectValue placeholder="Add company" />
                  </div>
                </SelectTrigger>
                <SelectContent>
                  {available.map((c) => (
                    <SelectItem key={c.id} value={c.id} className="text-sm">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{c.symbol}</span>
                        <span className="text-gray-400">·</span>
                        <span className="text-gray-500">{c.name}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          {/* Selected Company Cards */}
          {selectedData.length > 0 ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
              {selectedData.map((company, idx) => {
                const latest = company.financials[0];
                const sectorStyle = SECTOR_STYLES[company.sector] || "bg-gray-50 border-gray-200 text-gray-700";
                return (
                  <div
                    key={company.id}
                    className="relative bg-white rounded-2xl border-2 p-4 transition-all"
                    style={{ borderColor: COMPANY_COLORS[idx] + "33" }}
                  >
                    <button
                      onClick={() => handleRemoveCompany(company.id)}
                      className="absolute top-2 right-2 size-6 rounded-full bg-gray-100 hover:bg-red-50 flex items-center justify-center transition-colors"
                    >
                      <X className="size-3.5 text-gray-500 hover:text-red-500" />
                    </button>
                    <div
                      className="size-10 rounded-xl flex items-center justify-center text-white font-bold mb-3 shadow-sm"
                      style={{ backgroundColor: COMPANY_COLORS[idx] }}
                    >
                      {company.symbol.charAt(0)}
                    </div>
                    <div className="font-semibold text-gray-900 text-sm truncate mb-0.5">{company.symbol}</div>
                    <div className={`text-xs px-2 py-0.5 rounded-full border inline-block ${sectorStyle} mb-2`}>
                      {company.sector.split(" ")[0]}
                    </div>
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-gray-400">ROCE</span>
                        <span className="font-medium text-gray-700">{latest.roce}%</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-gray-400">OPM</span>
                        <span className="font-medium text-gray-700">{latest.opm}%</span>
                      </div>
                    </div>
                  </div>
                );
              })}

              {/* Add placeholder cards */}
              {selectedCompanies.length < 5 && Array.from({ length: Math.min(2, 5 - selectedCompanies.length) }).map((_, i) => (
                <button
                  key={`placeholder-${i}`}
                  className="bg-gray-50 rounded-2xl border-2 border-dashed border-gray-200 p-4 flex flex-col items-center justify-center gap-2 text-gray-400 hover:border-indigo-300 hover:text-indigo-500 transition-all min-h-[140px]"
                  onClick={() => {}}
                >
                  <div className="size-10 rounded-xl border-2 border-dashed border-current flex items-center justify-center">
                    <Plus className="size-5" />
                  </div>
                  <span className="text-xs">Add Company</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="size-16 rounded-2xl bg-indigo-50 flex items-center justify-center mb-4">
                <BarChart3 className="size-8 text-indigo-400" />
              </div>
              <h3 className="font-semibold text-gray-900 mb-1">No companies selected</h3>
              <p className="text-sm text-gray-400 max-w-xs">
                Select companies from the dropdown above to start comparing their financials.
              </p>
            </div>
          )}
        </div>

        {/* Quick Presets */}
        {selectedCompanies.length === 0 && (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-semibold text-gray-900 mb-4 text-sm">Quick Comparisons</h3>
            <div className="grid sm:grid-cols-3 gap-3">
              {[
                { label: "IT Giants", companies: ["tcs", "infosys", "wipro"], icon: "💻" },
                { label: "HDFC vs Reliance", companies: ["hdfc", "reliance"], icon: "⚡" },
                { label: "All Companies", companies: ["reliance", "tcs", "infosys", "hdfc", "asianpaints"], icon: "📊" },
              ].map((preset, idx) => (
                <button
                  key={idx}
                  onClick={() => setSelectedCompanies(preset.companies)}
                  className="flex items-center gap-3 p-4 rounded-xl border border-gray-100 hover:border-indigo-200 hover:bg-indigo-50/50 transition-all text-left"
                >
                  <span className="text-2xl">{preset.icon}</span>
                  <div>
                    <div className="font-semibold text-gray-900 text-sm">{preset.label}</div>
                    <div className="text-xs text-gray-400 mt-0.5">
                      {preset.companies.map((id) => getCompanyById(id)?.symbol).join(", ")}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Comparison Table */}
        {selectedCompanies.length >= 2 && (
          <ComparisonTable companyIds={selectedCompanies} />
        )}

        {/* Winner Summary */}
        {selectedCompanies.length >= 2 && (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
            <div className="flex items-center gap-2 mb-4">
              <Trophy className="size-5 text-amber-500" />
              <h3 className="font-semibold text-gray-900">Category Leaders</h3>
            </div>
            <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: "Highest Revenue", metric: "sales", higherBetter: true, unit: "B" },
                { label: "Best OPM", metric: "opm", higherBetter: true, unit: "%" },
                { label: "Highest ROCE", metric: "roce", higherBetter: true, unit: "%" },
                { label: "Lowest D/E", metric: "de", higherBetter: false, unit: "x" },
              ].map((cat, idx) => {
                const vals = selectedData.map((c) => ({
                  company: c,
                  val: c.financials[0][cat.metric as keyof typeof c.financials[0]] as number,
                }));
                const winner = cat.higherBetter
                  ? vals.reduce((a, b) => (a.val > b.val ? a : b))
                  : vals.reduce((a, b) => (a.val < b.val ? a : b));
                const winnerIdx = selectedData.indexOf(winner.company);

                return (
                  <div key={idx} className="bg-amber-50/50 rounded-xl border border-amber-100 p-4">
                    <div className="text-xs text-gray-400 mb-2">{cat.label}</div>
                    <div className="flex items-center gap-2">
                      <div
                        className="size-8 rounded-lg flex items-center justify-center text-white font-bold text-sm"
                        style={{ backgroundColor: COMPANY_COLORS[winnerIdx] }}
                      >
                        {winner.company.symbol.charAt(0)}
                      </div>
                      <div>
                        <div className="font-semibold text-gray-900 text-sm">{winner.company.symbol}</div>
                        <div className="text-xs text-amber-600 font-medium">
                          {cat.metric === "sales"
                            ? `₹${(winner.val / 1000).toFixed(0)}${cat.unit}`
                            : `${winner.val}${cat.unit}`}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}