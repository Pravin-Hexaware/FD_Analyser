import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Database, CheckCircle, RefreshCw, FileText, Plus,
  Pencil, Trash2, Download, Play, Activity, XCircle,
  Clock, Zap, Server, Cpu, HardDrive, AlertCircle,
  ChevronDown, ChevronUp, Check, X, Upload, BarChart3
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { companies as initialCompanies } from "../data/companies";
import type { CompanyData } from "../data/companies";
import { AppShell } from "../components/AppShell";
import { toast } from "sonner";

interface IngestionLog {
  id: string;
  company: string;
  status: "success" | "error" | "processing" | "pending";
  timestamp: Date;
  recordsProcessed: number;
  message?: string;
}

const SECTORS = ["Energy", "Technology", "Consumer Goods", "Financial Services", "Healthcare", "FMCG", "Auto", "Infra"];

const STATUS_CONFIG = {
  success: { icon: CheckCircle, color: "text-emerald-600", bg: "bg-emerald-50 border-emerald-200", badge: "bg-emerald-100 text-emerald-700" },
  error: { icon: XCircle, color: "text-red-600", bg: "bg-red-50 border-red-200", badge: "bg-red-100 text-red-700" },
  processing: { icon: RefreshCw, color: "text-blue-600", bg: "bg-blue-50 border-blue-200", badge: "bg-blue-100 text-blue-700" },
  pending: { icon: Clock, color: "text-gray-500", bg: "bg-gray-50 border-gray-200", badge: "bg-gray-100 text-gray-600" },
};

const sampleLogs: IngestionLog[] = [
  { id: "1", company: "Reliance Industries Ltd", status: "success", timestamp: new Date(2026, 2, 25, 10, 30), recordsProcessed: 240, message: "All parameters extracted successfully" },
  { id: "2", company: "TCS", status: "success", timestamp: new Date(2026, 2, 25, 10, 25), recordsProcessed: 240, message: "XBRL parsing completed" },
  { id: "3", company: "Infosys Ltd", status: "success", timestamp: new Date(2026, 2, 25, 10, 20), recordsProcessed: 240, message: "5-year historical data loaded" },
  { id: "4", company: "Asian Paints Ltd", status: "success", timestamp: new Date(2026, 2, 25, 10, 15), recordsProcessed: 240, message: "Balance sheet & P&L parsed" },
  { id: "5", company: "HDFC Bank Ltd", status: "success", timestamp: new Date(2026, 2, 25, 10, 10), recordsProcessed: 240, message: "Financial ratios computed" },
];

export default function AdminPage() {
  const navigate = useNavigate();
  const [isCollecting, setIsCollecting] = useState(false);
  const [isExtracting, setIsExtracting] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [companies, setCompanies] = useState<CompanyData[]>([...initialCompanies]);
  const [logs, setLogs] = useState<IngestionLog[]>(sampleLogs);
  const [liveLog, setLiveLog] = useState<string[]>([]);
  const logRef = useRef<HTMLDivElement>(null);

  const [newCompany, setNewCompany] = useState({ name: "", symbol: "", bseCode: "", sector: "", industry: "" });

  const systemServices = [
    { name: "Database Connection", desc: "PostgreSQL / Supabase", status: "operational", icon: HardDrive, latency: "12ms" },
    { name: "XBRL Processor", desc: "BSE filing parser v2.4", status: "operational", icon: Cpu, latency: "—" },
    { name: "AI/LLM Gateway", desc: "OpenAI GPT-4 · Gemini fallback", status: "operational", icon: Zap, latency: "340ms" },
    { name: "Cache Layer", desc: "Redis in-memory store", status: "operational", icon: Server, latency: "2ms" },
  ];

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [liveLog]);

  const addLiveLine = (text: string) => {
    setLiveLog((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${text}`]);
  };

  const handleStartCollection = () => {
    setIsCollecting(true);
    setLiveLog([]);

    const steps = [
      "Initializing XBRL collection pipeline...",
      "Connecting to BSE data feed...",
      "Fetching filings for Reliance Industries...",
      "  → Parsed 240 parameters (Balance Sheet, P&L, Cash Flow)",
      "Fetching filings for TCS...",
      "  → Parsed 240 parameters (5Y historical data)",
      "Fetching filings for Infosys...",
      "  → Parsed 240 parameters",
      "Fetching filings for HDFC Bank...",
      "  → Parsed 240 parameters (NBFC-adjusted ratios)",
      "Fetching filings for Asian Paints...",
      "  → Parsed 240 parameters",
      "Fetching filings for Wipro...",
      "  → Parsed 240 parameters",
      "Running data validation & normalization...",
      "Computing financial ratios & KPIs...",
      "Updating vector embeddings for AI search...",
      "✓ Collection complete. 1,440 records processed across 6 companies.",
    ];

    let i = 0;
    const interval = setInterval(() => {
      if (i < steps.length) {
        addLiveLine(steps[i]);
        i++;
      } else {
        clearInterval(interval);
        setIsCollecting(false);
        const newLog: IngestionLog = {
          id: String(logs.length + 1),
          company: "All Companies (Batch)",
          status: "success",
          timestamp: new Date(),
          recordsProcessed: 1440,
          message: "Full batch collection completed",
        };
        setLogs((prev) => [newLog, ...prev]);
        toast.success("XBRL collection complete!", { description: "1,440 records processed across 6 companies." });
      }
    }, 200);
  };

  const handleExtractParameters = () => {
    setIsExtracting(true);
    setTimeout(() => {
      setIsExtracting(false);
      toast.success("Parameters extracted!", { description: "240 parameters mapped per company." });
    }, 2000);
  };

  const handleAddCompany = () => {
    if (!newCompany.name || !newCompany.symbol) return;
    const company: CompanyData = {
      id: newCompany.symbol.toLowerCase(),
      name: newCompany.name,
      symbol: newCompany.symbol.toUpperCase(),
      bseCode: newCompany.bseCode,
      sector: newCompany.sector,
      industry: newCompany.industry,
      xbrlLink: "",
      financials: [],
    };
    setCompanies((prev) => [...prev, company]);
    setNewCompany({ name: "", symbol: "", bseCode: "", sector: "", industry: "" });
    setShowAddForm(false);
    toast.success(`${company.name} added to master list.`);
  };

  const handleDelete = (id: string) => {
    setCompanies((prev) => prev.filter((c) => c.id !== id));
    toast.success("Company removed.");
  };

  const statsCards = [
    { label: "Companies Tracked", value: companies.length, icon: Database, color: "indigo", sub: "+1 this month" },
    { label: "XBRL Files Processed", value: companies.length * 5, icon: FileText, color: "teal", sub: "5Y per company" },
    { label: "Parameters Extracted", value: companies.length * 40, icon: Activity, color: "purple", sub: "40 KPIs per year" },
    { label: "Total Records", value: (companies.length * 5 * 40).toLocaleString(), icon: BarChart3, color: "orange", sub: "Ready for AI" },
  ];

  const colorMap: Record<string, { bg: string; icon: string; ring: string }> = {
    indigo: { bg: "bg-indigo-50", icon: "text-indigo-600", ring: "bg-indigo-100" },
    teal: { bg: "bg-teal-50", icon: "text-teal-600", ring: "bg-teal-100" },
    purple: { bg: "bg-purple-50", icon: "text-purple-600", ring: "bg-purple-100" },
    orange: { bg: "bg-orange-50", icon: "text-orange-600", ring: "bg-orange-100" },
  };

  return (
    <AppShell
      breadcrumb={[{ label: "Dashboard", href: "/" }, { label: "Admin" }]}
      title="Admin Dashboard"
      subtitle="Manage companies, XBRL data pipelines, and system monitoring"
      actions={
        <>
          <Button variant="outline" size="sm" onClick={() => toast.success("Data exported!")} className="text-xs">
            <Download className="size-3.5 mr-1.5" />
            Export
          </Button>
          <Button variant="outline" size="sm" onClick={() => window.location.reload()} className="text-xs">
            <RefreshCw className="size-3.5 mr-1.5" />
            Refresh
          </Button>
        </>
      }
    >
      <div className="p-6 space-y-6">

        {/* ── Stats Cards ─────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {statsCards.map((card, idx) => {
            const c = colorMap[card.color];
            return (
              <div key={idx} className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
                <div className="flex items-center justify-between mb-3">
                  <div className={`size-10 rounded-xl ${c.ring} flex items-center justify-center`}>
                    <card.icon className={`size-5 ${c.icon}`} />
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-semibold text-gray-900">{card.value}</div>
                  </div>
                </div>
                <div className="text-sm font-medium text-gray-700">{card.label}</div>
                <div className="text-xs text-gray-400 mt-0.5">{card.sub}</div>
              </div>
            );
          })}
        </div>

        {/* ── XBRL Data Pipeline ──────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-50 flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-gray-900">XBRL Data Pipeline</h2>
              <p className="text-xs text-gray-400 mt-0.5">Collect and process financial filings from BSE</p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleExtractParameters}
                disabled={isExtracting}
                className="text-xs"
              >
                <Upload className={`size-3.5 mr-1.5 ${isExtracting ? "animate-bounce" : ""}`} />
                {isExtracting ? "Extracting..." : "Extract Parameters"}
              </Button>
              <Button
                size="sm"
                onClick={handleStartCollection}
                disabled={isCollecting}
                className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs"
              >
                <Play className={`size-3.5 mr-1.5 ${isCollecting ? "animate-pulse" : ""}`} />
                {isCollecting ? "Collecting..." : "Run XBRL Collection"}
              </Button>
            </div>
          </div>

          <div className="grid md:grid-cols-2 divide-x divide-gray-50">
            {/* Live Log */}
            <div className="p-5">
              <div className="flex items-center gap-2 mb-3">
                <div className={`size-2 rounded-full ${isCollecting ? "bg-blue-500 animate-pulse" : "bg-gray-300"}`} />
                <span className="text-sm font-medium text-gray-700">Live Output</span>
              </div>
              <div
                ref={logRef}
                className="h-48 bg-slate-950 rounded-xl p-4 overflow-y-auto font-mono text-xs"
              >
                {liveLog.length === 0 ? (
                  <div className="text-slate-600">Ready. Press "Run XBRL Collection" to start...</div>
                ) : (
                  liveLog.map((line, idx) => (
                    <div
                      key={idx}
                      className={`mb-0.5 ${
                        line.includes("✓") ? "text-emerald-400" :
                        line.includes("→") ? "text-blue-300" :
                        line.includes("Error") ? "text-red-400" :
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
              <div className="text-sm font-medium text-gray-700 mb-3">Recent Runs</div>
              <div className="space-y-2 h-48 overflow-y-auto pr-1">
                {logs.slice(0, 6).map((log) => {
                  const sc = STATUS_CONFIG[log.status];
                  return (
                    <div key={log.id} className={`flex items-center justify-between p-3 rounded-xl border ${sc.bg}`}>
                      <div className="flex items-center gap-2.5 min-w-0">
                        <sc.icon className={`size-4 flex-shrink-0 ${sc.color} ${log.status === "processing" ? "animate-spin" : ""}`} />
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-gray-900 truncate">{log.company}</div>
                          <div className="text-xs text-gray-400">
                            {log.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {log.recordsProcessed} records
                          </div>
                        </div>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0 ml-2 ${sc.badge}`}>
                        {log.status}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

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
              <div className="grid grid-cols-5 gap-3 mb-3">
                {[
                  { key: "name", placeholder: "Company Name *" },
                  { key: "symbol", placeholder: "Symbol (BSE) *" },
                  { key: "bseCode", placeholder: "BSE Stripcode" },
                  { key: "sector", placeholder: "Sector" },
                  { key: "industry", placeholder: "Industry" },
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
                  {["Company", "Symbol", "BSE Code", "Sector", "Industry", "XBRL Status", "Actions"].map((h) => (
                    <th key={h} className={`px-5 py-3.5 text-xs font-semibold text-gray-500 uppercase tracking-wide ${h === "Actions" ? "text-right" : "text-left"}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {companies.map((company) => (
                  <tr key={company.id} className="hover:bg-gray-50/50 transition-colors group">
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-3">
                        <div className="size-8 rounded-lg bg-indigo-100 flex items-center justify-center flex-shrink-0">
                          <span className="text-indigo-600 font-semibold text-xs">{company.symbol.charAt(0)}</span>
                        </div>
                        <div>
                          <div className="font-medium text-gray-900 text-sm">{company.name}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <span className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded-md text-xs font-mono font-medium">
                        {company.symbol}
                      </span>
                    </td>
                    <td className="px-5 py-4 text-gray-500 text-xs font-mono">{company.bseCode}</td>
                    <td className="px-5 py-4">
                      <span className="text-sm text-gray-600">{company.sector}</span>
                    </td>
                    <td className="px-5 py-4 text-gray-500 text-sm">{company.industry}</td>
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-1.5">
                        <div className="size-1.5 rounded-full bg-emerald-500" />
                        <span className="text-xs text-emerald-600 font-medium">Active</span>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => toast.info(`Edit ${company.name}`)}
                          className="size-8 rounded-lg hover:bg-gray-100 flex items-center justify-center transition-colors"
                        >
                          <Pencil className="size-3.5 text-gray-500" />
                        </button>
                        <button
                          onClick={() => handleDelete(company.id)}
                          className="size-8 rounded-lg hover:bg-red-50 flex items-center justify-center transition-colors"
                        >
                          <Trash2 className="size-3.5 text-red-400" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── System Status ────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-50">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-semibold text-gray-900">System Status</h2>
                <p className="text-xs text-gray-400 mt-0.5">All services operational</p>
              </div>
              <div className="flex items-center gap-2 px-3 py-1.5 bg-emerald-50 border border-emerald-200 rounded-full">
                <div className="size-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-xs text-emerald-700 font-medium">All Systems Operational</span>
              </div>
            </div>
          </div>

          <div className="divide-y divide-gray-50">
            {systemServices.map((svc, idx) => (
              <div key={idx} className="px-6 py-4 flex items-center justify-between hover:bg-gray-50/30 transition-colors">
                <div className="flex items-center gap-4">
                  <div className="size-10 rounded-xl bg-emerald-50 flex items-center justify-center">
                    <svc.icon className="size-5 text-emerald-600" />
                  </div>
                  <div>
                    <div className="font-medium text-gray-900 text-sm">{svc.name}</div>
                    <div className="text-xs text-gray-400">{svc.desc}</div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  {svc.latency !== "—" && (
                    <div className="text-right">
                      <div className="text-xs text-gray-400">Latency</div>
                      <div className="text-sm font-medium text-gray-700">{svc.latency}</div>
                    </div>
                  )}
                  <div className="flex items-center gap-2 px-3 py-1.5 bg-emerald-50 border border-emerald-200 rounded-full">
                    <CheckCircle className="size-3.5 text-emerald-600" />
                    <span className="text-xs text-emerald-700 font-medium">Operational</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </AppShell>
  );
}
