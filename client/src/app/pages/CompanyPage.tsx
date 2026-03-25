import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Download, MessageSquare, TrendingUp, TrendingDown,
  Sparkles, Building2, Hash, ArrowUpRight
} from "lucide-react";
import { Button } from "../components/ui/button";
import { getCompanyById } from "../data/companies";
import { FinancialTable } from "../components/FinancialTable";
import { AppShell } from "../components/AppShell";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from "recharts";
import { toast } from "sonner";

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

const tabs = ["Overview", "Financials", "Analytics"];

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("Overview");
  const company = getCompanyById(id || "");

  if (!company) {
    return (
      <AppShell title="Company Not Found">
        <div className="flex items-center justify-center h-64">
          <div className="text-center">
            <div className="text-gray-400 text-lg mb-3">Company not found</div>
            <Button onClick={() => navigate("/")} className="bg-indigo-600 hover:bg-indigo-700 text-white">
              Go Home
            </Button>
          </div>
        </div>
      </AppShell>
    );
  }

  const latest = company.financials[0];
  const oldest = company.financials[company.financials.length - 1];
  const prev = company.financials[1];

  const salesGrowthYoY = (((latest.sales - prev.sales) / prev.sales) * 100).toFixed(1);
  const patGrowthYoY = (((latest.pat - prev.pat) / prev.pat) * 100).toFixed(1);
  const sales5YCAGR = ((Math.pow(latest.sales / oldest.sales, 0.2) - 1) * 100).toFixed(1);

  const chartData = [...company.financials].reverse().map((f) => ({
    year: `FY${f.year}`,
    "Revenue": +(f.sales / 1000).toFixed(1),
    "PAT": +(f.pat / 1000).toFixed(1),
    "EBITDA": +(f.ebitda / 1000).toFixed(1),
    "ROCE": f.roce,
    "OPM": f.opm,
    "D/E": f.de,
  }));

  const sectorClass = SECTOR_COLORS[company.sector] || "bg-gray-100 text-gray-700 border-gray-200";

  const kpis = [
    {
      label: `Revenue FY${latest.year}`,
      value: `₹${(latest.sales / 1000).toFixed(0)}B`,
      change: `+${salesGrowthYoY}% YoY`,
      up: Number(salesGrowthYoY) >= 0,
      sub: `5Y CAGR: ${sales5YCAGR}%`,
    },
    {
      label: `PAT FY${latest.year}`,
      value: `₹${(latest.pat / 1000).toFixed(0)}B`,
      change: `+${patGrowthYoY}% YoY`,
      up: Number(patGrowthYoY) >= 0,
      sub: `EPS: ₹${latest.eps}`,
    },
    {
      label: "ROCE",
      value: `${latest.roce}%`,
      change: latest.roce > 20 ? "Excellent" : "Good",
      up: latest.roce > 15,
      sub: "Return on Capital",
    },
    {
      label: "OPM",
      value: `${latest.opm}%`,
      change: latest.opm > 25 ? "High Margin" : "Stable",
      up: true,
      sub: "Operating Margin",
    },
    {
      label: "D/E Ratio",
      value: `${latest.de}x`,
      change: latest.de < 1 ? "Low Leverage" : "Moderate",
      up: latest.de < 1,
      sub: "Debt-to-Equity",
    },
    {
      label: "CFO",
      value: `₹${(latest.cfo / 1000).toFixed(0)}B`,
      change: `${((latest.cfo / latest.pat) * 100).toFixed(0)}% of PAT`,
      up: latest.cfo > latest.pat * 0.8,
      sub: "Cash from Operations",
    },
  ];

  return (
    <AppShell
      breadcrumb={[
        { label: "Dashboard", href: "/" },
        { label: company.sector, href: "/" },
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
          <Button
            size="sm"
            onClick={() => toast.success("Report downloaded!")}
            className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs"
          >
            <Download className="size-3.5 mr-1.5" />
            Export
          </Button>
        </>
      }
    >
      <div className="p-6">
        {/* Company Header */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 mb-6">
          <div className="flex items-start justify-between mb-4">
            <div className="flex items-start gap-4">
              <div className="size-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center shadow-md shadow-indigo-200 flex-shrink-0">
                <span className="text-white font-bold text-lg">{company.symbol.charAt(0)}</span>
              </div>
              <div>
                <h1 className="text-xl font-semibold text-gray-900 mb-1">{company.name}</h1>
                <div className="flex items-center gap-3 flex-wrap">
                  <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${sectorClass}`}>
                    <Building2 className="size-3" />
                    {company.sector}
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-gray-500 bg-gray-50 px-2.5 py-1 rounded-full border border-gray-100">
                    <Hash className="size-3" />
                    BSE {company.bseCode}
                  </div>
                  <div className="text-xs text-gray-400">
                    {company.industry}
                  </div>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                onClick={() => navigate(`/report/${company.id}`)}
                className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs"
              >
                <Sparkles className="size-3.5 mr-1.5" />
                AI Report
              </Button>
            </div>
          </div>

          {/* KPI Grid */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {kpis.map((kpi, idx) => (
              <div key={idx} className="bg-gray-50/80 rounded-xl p-3.5 border border-gray-100">
                <div className="text-xs text-gray-400 mb-1 truncate">{kpi.label}</div>
                <div className="text-lg font-semibold text-gray-900 mb-1">{kpi.value}</div>
                <div className={`flex items-center gap-1 text-xs ${kpi.up ? "text-emerald-500" : "text-red-500"}`}>
                  {kpi.up ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
                  {kpi.change}
                </div>
                <div className="text-xs text-gray-400 mt-0.5">{kpi.sub}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 mb-6 bg-white border border-gray-100 rounded-xl p-1.5 w-fit shadow-sm">
          {tabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-5 py-2 rounded-lg text-sm font-medium transition-all ${
                activeTab === tab
                  ? "bg-indigo-600 text-white shadow-sm shadow-indigo-200"
                  : "text-gray-500 hover:text-gray-900 hover:bg-gray-50"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        {activeTab === "Overview" && (
          <div className="grid md:grid-cols-2 gap-5">
            {/* Revenue Chart */}
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900 text-sm">Revenue & Profit Trend</h3>
                <div className="flex items-center gap-1.5">
                  <div className="size-2.5 rounded-full bg-indigo-500" />
                  <span className="text-xs text-gray-400">Revenue</span>
                  <div className="size-2.5 rounded-full bg-teal-500 ml-2" />
                  <span className="text-xs text-gray-400">PAT</span>
                </div>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData}>
                    <defs>
                      <linearGradient id="revenue" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#4f46e5" stopOpacity={0.15} />
                        <stop offset="95%" stopColor="#4f46e5" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="pat" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#0d9488" stopOpacity={0.15} />
                        <stop offset="95%" stopColor="#0d9488" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="year" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, fontSize: 12 }}
                      formatter={(v: any) => [`₹${v}B`, ""]}
                    />
                    <Area type="monotone" dataKey="Revenue" stroke="#4f46e5" fill="url(#revenue)" strokeWidth={2.5} />
                    <Area type="monotone" dataKey="PAT" stroke="#0d9488" fill="url(#pat)" strokeWidth={2.5} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* ROCE & OPM */}
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900 text-sm">Profitability Ratios</h3>
                <div className="flex items-center gap-1.5">
                  <div className="size-2.5 rounded-full bg-purple-500" />
                  <span className="text-xs text-gray-400">ROCE</span>
                  <div className="size-2.5 rounded-full bg-amber-500 ml-2" />
                  <span className="text-xs text-gray-400">OPM</span>
                </div>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="year" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, fontSize: 12 }}
                      formatter={(v: any) => [`${v}%`, ""]}
                    />
                    <Line type="monotone" dataKey="ROCE" stroke="#7c3aed" strokeWidth={2.5} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                    <Line type="monotone" dataKey="OPM" stroke="#f59e0b" strokeWidth={2.5} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* EBITDA Bar */}
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
              <h3 className="font-semibold text-gray-900 text-sm mb-4">EBITDA Growth</h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="year" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, fontSize: 12 }}
                      formatter={(v: any) => [`₹${v}B`, "EBITDA"]}
                    />
                    <Bar dataKey="EBITDA" fill="#6366f1" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* D/E Trend */}
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
              <h3 className="font-semibold text-gray-900 text-sm mb-4">Leverage Trend (D/E)</h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="year" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, fontSize: 12 }}
                      formatter={(v: any) => [`${v}x`, "D/E"]}
                    />
                    <Bar dataKey="D/E" fill="#f59e0b" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}

        {activeTab === "Financials" && (
          <div className="space-y-5">
            <FinancialTable companyId={company.id} years={5} />

            {/* XBRL Source */}
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-semibold text-gray-900 text-sm mb-1">Data Source</h3>
                  <p className="text-xs text-gray-400">
                    Financial data is sourced from BSE XBRL filings processed by FinBot.
                  </p>
                </div>
                <a
                  href={company.xbrlLink}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-sm text-indigo-600 hover:text-indigo-700 transition-colors"
                >
                  <span>View XBRL</span>
                  <ArrowUpRight className="size-4" />
                </a>
              </div>
            </div>
          </div>
        )}

        {activeTab === "Analytics" && (
          <div className="space-y-5">
            {/* Performance Score Card */}
            <div className="grid md:grid-cols-3 gap-5">
              {[
                {
                  title: "Profitability Score",
                  score: Math.min(Math.round((latest.opm / 35) * 100), 100),
                  color: "indigo",
                  items: [`OPM: ${latest.opm}%`, `ROCE: ${latest.roce}%`, `EPS: ₹${latest.eps}`],
                },
                {
                  title: "Financial Health",
                  score: Math.min(Math.round((1 / (latest.de + 0.1)) * 50 + 50), 100),
                  color: "emerald",
                  items: [`D/E: ${latest.de}x`, `CFO: ₹${(latest.cfo / 1000).toFixed(0)}B`, `CFO/PAT: ${((latest.cfo / latest.pat) * 100).toFixed(0)}%`],
                },
                {
                  title: "Growth Quality",
                  score: Math.min(Math.round(parseFloat(sales5YCAGR) * 3), 100),
                  color: "purple",
                  items: [`5Y CAGR: ${sales5YCAGR}%`, `Revenue: ₹${(latest.sales / 1000).toFixed(0)}B`, `PAT: ₹${(latest.pat / 1000).toFixed(0)}B`],
                },
              ].map((s, idx) => {
                const colorMap: Record<string, { ring: string; bar: string; bg: string }> = {
                  indigo: { ring: "text-indigo-600", bar: "bg-indigo-500", bg: "bg-indigo-50" },
                  emerald: { ring: "text-emerald-600", bar: "bg-emerald-500", bg: "bg-emerald-50" },
                  purple: { ring: "text-purple-600", bar: "bg-purple-500", bg: "bg-purple-50" },
                };
                const c = colorMap[s.color];
                return (
                  <div key={idx} className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="font-semibold text-gray-900 text-sm">{s.title}</h3>
                      <div className={`text-2xl font-semibold ${c.ring}`}>{s.score}</div>
                    </div>
                    <div className="h-2 bg-gray-100 rounded-full mb-4">
                      <div
                        className={`h-full ${c.bar} rounded-full transition-all`}
                        style={{ width: `${s.score}%` }}
                      />
                    </div>
                    <ul className="space-y-1.5">
                      {s.items.map((item, i) => (
                        <li key={i} className="flex items-center gap-2 text-sm text-gray-600">
                          <div className={`size-1.5 rounded-full ${c.bar}`} />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>

            {/* CFO vs PAT */}
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
              <h3 className="font-semibold text-gray-900 text-sm mb-4">Cash Flow Quality (CFO vs PAT)</h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} barGap={4}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="year" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, fontSize: 12 }}
                      formatter={(v: any) => [`₹${v}B`, ""]}
                    />
                    <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="PAT" fill="#4f46e5" radius={[4, 4, 0, 0]} name="PAT" />
                    <Bar dataKey="Revenue" fill="#e0e7ff" radius={[4, 4, 0, 0]} name="Revenue" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}