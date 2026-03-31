import { useState, useEffect, useRef } from "react";
import {
  Database, CheckCircle, RefreshCw, FileText, Plus,
  Play, Activity, XCircle,
  Clock, Check, X, Upload, BarChart3, ChevronDown, Edit2, Trash2
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import type { CompanyData } from "../data/companies";
import { AppShell } from "../components/AppShell";
import { toast } from "react-hot-toast";
import { apiClient } from "../../api/apiClient";
import { useExtraction } from "../../context/ExtractionContext";

// interface IngestionLog {
//   id: string;
//   company: string;
//   status: "success" | "error" | "processing" | "pending";
//   timestamp: Date;
//   recordsProcessed: number;
//   message?: string;
// }

const STATUS_CONFIG = {
  success: { icon: CheckCircle, color: "text-emerald-600", bg: "bg-emerald-50 border-emerald-200", badge: "bg-emerald-100 text-emerald-700" },
  error: { icon: XCircle, color: "text-red-600", bg: "bg-red-50 border-red-200", badge: "bg-red-100 text-red-700" },
  processing: { icon: RefreshCw, color: "text-blue-600", bg: "bg-blue-50 border-blue-200", badge: "bg-blue-100 text-blue-700" },
  pending: { icon: Clock, color: "text-gray-500", bg: "bg-gray-50 border-gray-200", badge: "bg-gray-100 text-gray-600" },
};

export default function AdminPage() {
  const { isCollecting, isExtractingData, liveLog, logs, startXbrlExtraction, startDataExtraction, stopExtraction, clearLiveLog, clearLogs, setOnCompanyExtracted } = useExtraction();
  const [showAddForm, setShowAddForm] = useState(false);
  const [companies, setCompanies] = useState<CompanyData[]>([]);
  const [expandedSource, setExpandedSource] = useState<string | null>(null);
  const [showDataSourcesDropdown, setShowDataSourcesDropdown] = useState(true);
  const [showAddSourceForm, setShowAddSourceForm] = useState(false);
  const [editingSourceId, setEditingSourceId] = useState<string | null>(null);
  const [dataSources, setDataSources] = useState([
    { id: "bse", name: "BSE Filings", status: "Active", standard: "XBRL", formats: "XML, HTML", period: "Quarterly / Annually" }
  ]);
  const [newSource, setNewSource] = useState({ name: "", standard: "", formats: "" });
  const logRef = useRef<HTMLDivElement>(null);

  const [newCompany, setNewCompany] = useState({ name: "", symbol: "", bseCode: "", sector: "" });

  // Fetch companies from database on mount
  useEffect(() => {
    const loadCompanies = async () => {
      try {
        const dbCompanies = await apiClient.getAllCompanies();
        if (dbCompanies && dbCompanies.length > 0) {
          setCompanies(dbCompanies as any);
        }
      } catch (error) {
        console.error("Failed to load companies from database:", error);
      }
    };

    loadCompanies();
  }, []);

  // Set up callback to add extracted companies to the list
  useEffect(() => {
    if (setOnCompanyExtracted) {
      setOnCompanyExtracted((company: any) => {
        // Add newly extracted company to the companies list
        setCompanies((prev) => {
          // Check if company already exists
          const exists = prev.some((c) => c.bseCode === company.bseCode || c.id === company.id);
          if (exists) return prev;
          
          // Add new company
          return [...prev, {
            id: company.id || company.bseCode,
            name: company.name || company.company_name,
            symbol: company.symbol,
            bseCode: company.bseCode || company.scrip_code,
            sector: company.sector || "Unknown",
            industry: company.industry || "",
            xbrlLink: "",
            financials: [],
          }];
        });
      });
    }
  }, [setOnCompanyExtracted]);

  const handleAddCompany = () => {
    if (!newCompany.name || !newCompany.symbol) return;
    const company: any = {
      id: newCompany.symbol.toLowerCase(),
      name: newCompany.name,
      symbol: newCompany.symbol.toUpperCase(),
      bseCode: newCompany.bseCode,
      sector: newCompany.sector,
      xbrlLink: "",
      financials: [],
    };
    setCompanies((prev) => [...prev, company]);
    setNewCompany({ name: "", symbol: "", bseCode: "", sector: "" });
    setShowAddForm(false);
    toast.success(`${company.name} added to master list.`);
  };

  const handleAddDataSource = () => {
    if (!newSource.name) return;
    const source = {
      id: newSource.name.toLowerCase().replace(/\s+/g, "-"),
      name: newSource.name,
      status: "Active",
      standard: "XBRL",
      formats: newSource.formats || "XML",
      period: "Quarterly / Annually"
    };
    setDataSources((prev) => [...prev, source]);
    setNewSource({ name: "", standard: "", formats: "" });
    setShowAddSourceForm(false);
    toast.success(`${source.name} added to data sources.`);
  };

  const handleEditDataSource = (sourceId: string) => {
    const source = dataSources.find(s => s.id === sourceId);
    if (source) {
      setNewSource({ name: source.name, standard: source.standard, formats: source.formats });
      setEditingSourceId(sourceId);
      setShowAddSourceForm(true);
    }
  };

  const handleSaveEditDataSource = () => {
    if (!newSource.name || !editingSourceId) return;
    setDataSources((prev) =>
      prev.map((s) =>
        s.id === editingSourceId
          ? { ...s, name: newSource.name, formats: newSource.formats }
          : s
      )
    );
    setNewSource({ name: "", standard: "", formats: "" });
    setEditingSourceId(null);
    setShowAddSourceForm(false);
    toast.success("Data source updated successfully.");
  };

  const handleDeleteDataSource = (sourceId: string) => {
    if (sourceId === "bse") {
      toast.error("Cannot delete default BSE Filings source.");
      return;
    }
    setDataSources((prev) => prev.filter((s) => s.id !== sourceId));
    if (expandedSource === sourceId) setExpandedSource(null);
    toast.success("Data source deleted successfully.");
  };

  return (
    <AppShell
      breadcrumb={[{ label: "Dashboard", href: "/" }, { label: "Admin" }]}
      title="Admin Dashboard"
      subtitle="Manage companies, regulatory data sources, and financial pipelines"
      actions={
        <>
        </>
      }
    >
      <div className="p-6 space-y-6">

        {/* ── Data Sources ────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <button
            onClick={() => setShowDataSourcesDropdown(!showDataSourcesDropdown)}
            className="w-full px-6 py-3 border-b border-gray-50 flex items-center justify-between hover:bg-gray-50 transition-colors"
          >
            <h2 className="font-semibold text-gray-900 text-sm">Data Sources</h2>
            <ChevronDown 
              className={`size-4 text-gray-400 transition-transform ${showDataSourcesDropdown ? "rotate-180" : ""}`}
            />
          </button>

          {showDataSourcesDropdown && (
            <div className="space-y-1 p-3">
              {dataSources.map((source) => (
                <button
                  key={source.id}
                  onClick={() => setExpandedSource(expandedSource === source.id ? null : source.id)}
                  className="w-full text-left p-3 rounded-lg border border-gray-100 hover:border-emerald-300 hover:bg-emerald-50 transition-all cursor-pointer"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <div className="size-1.5 rounded-full bg-emerald-500 flex-shrink-0" />
                      <h3 className="font-medium text-gray-900 text-xs truncate">{source.name}</h3>
                      <span className="text-xs px-1.5 py-0.5 bg-emerald-50 text-emerald-700 rounded font-medium flex-shrink-0">{source.status}</span>
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0 ml-2">
                      {source.id !== "bse" && (
                        <>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleEditDataSource(source.id);
                            }}
                            className="p-1 rounded hover:bg-blue-100 transition-colors"
                            title="Edit"
                          >
                            <Edit2 className="size-3.5 text-blue-600" />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteDataSource(source.id);
                            }}
                            className="p-1 rounded hover:bg-red-100 transition-colors"
                            title="Delete"
                          >
                            <Trash2 className="size-3.5 text-red-600" />
                          </button>
                        </>
                      )}
                      <ChevronDown 
                        className={`size-3.5 text-gray-400 transition-transform ${expandedSource === source.id ? "rotate-180" : ""}`}
                      />
                    </div>
                  </div>
                  
                  {/* Expanded Details */}
                  {expandedSource === source.id && (
                    <div className="mt-2 pt-2 border-t border-emerald-200 grid grid-cols-3 gap-2">
                      <div>
                        <p className="text-xs font-semibold text-gray-700">Formats</p>
                        <p className="text-xs text-gray-900 mt-0.5">{source.formats}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold text-gray-700">Companies</p>
                        <p className="text-xs text-gray-900 mt-0.5">{companies.length}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold text-gray-700">Period</p>
                        <p className="text-xs text-gray-900 mt-0.5">{source.period}</p>
                      </div>
                    </div>
                  )}
                </button>
              ))}

              {/* Add New Data Source */}
              <div
                className="w-full text-left p-3 rounded-lg border border-dashed border-gray-300 hover:border-blue-300 hover:bg-blue-50 transition-all"
              >
                <button
                  onClick={() => {
                    setEditingSourceId(null);
                    setNewSource({ name: "", standard: "", formats: "" });
                    setShowAddSourceForm(!showAddSourceForm);
                  }}
                  className="w-full flex items-center gap-2"
                >
                  <Plus className="size-3.5 text-blue-600" />
                  <span className="text-xs font-medium text-blue-600">Add Data Source</span>
                </button>

                {showAddSourceForm && (
                  <div className="mt-2 pt-2 border-t border-blue-200 space-y-1.5" onClick={(e) => e.stopPropagation()}>
                    <Input
                      placeholder="Source name (e.g., NSE)"
                      value={newSource.name}
                      onChange={(e) => setNewSource({ ...newSource, name: e.target.value })}
                      className="text-xs h-8 bg-white border border-gray-300 text-gray-900 placeholder-gray-500"
                    />
                    <Input
                      placeholder="Formats (e.g., XML, HTML)"
                      value={newSource.formats}
                      onChange={(e) => setNewSource({ ...newSource, formats: e.target.value })}
                      className="text-xs h-8 bg-white border border-gray-300 text-gray-900 placeholder-gray-500"
                    />
                    <div className="flex gap-1.5 pt-1">
                      <Button
                        size="sm"
                        onClick={editingSourceId ? handleSaveEditDataSource : handleAddDataSource}
                        className="bg-blue-600 hover:bg-blue-700 text-white text-xs flex-1 h-7"
                      >
                        {editingSourceId ? "Update" : "Add"}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setShowAddSourceForm(false);
                          setEditingSourceId(null);
                          setNewSource({ name: "", standard: "", formats: "" });
                        }}
                        className="text-xs flex-1 h-7"
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── Regulatory Data Pipeline (Only visible when BSE is selected) ────────────────────────── */}
        {expandedSource === "bse" && (
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-50 flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-gray-900">Regulatory & Financial Data</h2>
              <p className="text-xs text-gray-400 mt-0.5">BSE financial and regulatory filings • Fetch and extract data</p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                onClick={startDataExtraction}
                disabled={isExtractingData || isCollecting}
                className="bg-teal-600 hover:bg-teal-700 text-white text-xs"
              >
                <Upload className={`size-3.5 mr-1.5 ${isExtractingData ? "animate-bounce" : ""}`} />
                {isExtractingData ? "Extracting..." : "Extract Metrics"}
              </Button>
              <Button
                size="sm"
                onClick={startXbrlExtraction}
                disabled={isCollecting}
                className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs"
              >
                <Play className={`size-3.5 mr-1.5 ${isCollecting ? "animate-pulse" : ""}`} />
                {isCollecting ? "Fetching..." : "Fetch Filings"}
              </Button>
              {(isCollecting || isExtractingData) && (
                <Button
                  size="sm"
                  onClick={stopExtraction}
                  className="text-xs bg-red-600 hover:bg-red-700 text-white"
                >
                  <X className="size-3.5 mr-1.5" />
                  Stop
                </Button>
              )}
            </div>
          </div>

          <div className="grid md:grid-cols-2 divide-x divide-gray-50">
            {/* Live Log */}
            <div className="p-5">
              <div className="flex items-center justify-between gap-2 mb-3">
                <div className="flex items-center gap-2">
                  <div className={`size-2 rounded-full ${isCollecting || isExtractingData ? "bg-blue-500 animate-pulse" : "bg-gray-300"}`} />
                  <span className="text-sm font-medium text-gray-700">Live Output</span>
                </div>
                <button
                  onClick={clearLiveLog}
                  className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  Clear
                </button>
              </div>
              <div
                ref={logRef}
                className="h-48 bg-slate-950 rounded-xl p-4 overflow-y-auto font-mono text-xs"
              >
                {liveLog.length === 0 ? (
                  <div className="text-slate-600">Ready. Click "Extract XBRLs" or "Extract Data" to start...</div>
                ) : (
                  liveLog.map((line, idx) => (
                    <div
                      key={idx}
                      className={`mb-0.5 ${
                        line.includes("✓") ? "text-emerald-400" :
                        line.includes("→") ? "text-blue-300" :
                        line.includes("✗") ? "text-red-400" :
                        line.includes("⊘") ? "text-yellow-400" :
                        line.includes("⟳") ? "text-purple-400" :
                        line.includes("📊") || line.includes("📄") ? "text-cyan-300" :
                        "text-slate-400"
                      }`}
                    >
                      {line}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Recent Runs */}
            <div className="p-5">
              <div className="flex items-center justify-between gap-2 mb-3">
                <div className="text-sm font-medium text-gray-700">Recent Runs</div>
                <button
                  onClick={clearLogs}
                  className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  Clear
                </button>
              </div>
              <div className="space-y-2 h-48 overflow-y-auto pr-1">
                {logs.length === 0 ? (
                  <div className="text-xs text-gray-400 text-center py-8">No runs yet</div>
                ) : (
                  logs.slice(0, 6).map((log: any) => {
                    const sc = STATUS_CONFIG[log.status as keyof typeof STATUS_CONFIG];
                    return (
                      <div key={log.id} className={`flex items-center justify-between p-3 rounded-xl border ${sc.bg}`}>
                        <div className="flex items-center gap-2.5 min-w-0">
                          <sc.icon className={`size-4 flex-shrink-0 ${sc.color} ${log.status === "processing" ? "animate-spin" : ""}`} />
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-gray-900 truncate">{log.company}</div>
                            <div className="text-xs text-gray-400">
                              {new Date(log.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {log.recordsProcessed} records
                            </div>
                          </div>
                        </div>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0 ml-2 ${sc.badge}`}>
                          {log.status}
                        </span>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </div>
        )}

        {/* ── Company Master List ──────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-50 flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-gray-900">Company Master List</h2>
              <p className="text-xs text-gray-400 mt-0.5">{companies.length} companies · Click + to add new</p>
            </div>
            <Button
              size="sm"
              onClick={() => setShowAddForm(!showAddForm)}
              className={showAddForm ? "bg-red-50 text-red-600 border border-red-200 hover:bg-red-100" : "bg-indigo-600 hover:bg-indigo-700 text-white text-xs"}
            >
              {showAddForm ? (
                <><X className="size-3.5 mr-1.5" />Cancel</>
              ) : (
                <><Plus className="size-3.5 mr-1.5" />Add Company</>
              )}
            </Button>
          </div>

          {/* Add Form */}
          {showAddForm && (
            <div className="px-6 py-4 bg-indigo-50/50 border-b border-indigo-100">
              <div className="grid grid-cols-4 gap-3 mb-3">
                {[
                  { key: "name", placeholder: "Company Name *" },
                  { key: "symbol", placeholder: "Symbol (BSE) *" },
                  { key: "bseCode", placeholder: "Scrip Code" },
                  { key: "sector", placeholder: "Sector" },
                ].map((field) => (
                  <Input
                    key={field.key}
                    placeholder={field.placeholder}
                    value={(newCompany as any)[field.key]}
                    onChange={(e) => setNewCompany({ ...newCompany, [field.key]: e.target.value })}
                    className="bg-white text-sm h-9"
                  />
                ))}
              </div>
              <div className="flex gap-2">
                <Button size="sm" onClick={handleAddCompany} className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs">
                  <Check className="size-3.5 mr-1.5" />
                  Save Company
                </Button>
                <Button size="sm" variant="outline" onClick={() => setShowAddForm(false)} className="text-xs">
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50/80 border-b border-gray-100">
                  {["Company", "Symbol", "Scrip Code", "Sector"].map((h) => (
                    <th key={h} className={`px-4 py-2.5 text-xs font-semibold text-gray-600 uppercase tracking-wide text-left`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {companies.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-gray-400 text-sm">
                      No companies found. Add one to get started.
                    </td>
                  </tr>
                ) : (
                  companies.map((company) => (
                    <tr key={company.id} className="hover:bg-blue-50/40 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="size-6 rounded bg-indigo-100 flex items-center justify-center flex-shrink-0">
                            <span className="text-indigo-600 font-bold text-xs">{company.symbol.charAt(0)}</span>
                          </div>
                          <span className="font-medium text-gray-800 text-xs">{company.name || (company as any).company_name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded text-xs font-mono font-semibold">
                          {company.symbol}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs text-gray-600 font-mono">{company.bseCode || (company as any).scripCode || (company as any).scrip_code}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs text-gray-600">{company.sector}</span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>


      </div>
    </AppShell>
  );
}
