import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search, TrendingUp, BarChart3, MessageSquare, Sparkles,
  ArrowRight, Building2, FileText, Users, ChevronRight,
  Database, Shield, Zap, TrendingDown
} from "lucide-react";
import { Button } from "../components/ui/button";
import { apiClient, type CompanySuggestion } from "../../api/apiClient";

const tickerItems = [
  { symbol: "RELIANCE", price: "₹2,945", change: "+2.5%", up: true },
  { symbol: "TCS", price: "₹3,812", change: "+1.8%", up: true },
  { symbol: "HDFCBANK", price: "₹1,658", change: "-0.5%", up: false },
  { symbol: "INFY", price: "₹1,478", change: "+3.2%", up: true },
  { symbol: "ASIANPAINT", price: "₹2,341", change: "-1.1%", up: false },
  { symbol: "WIPRO", price: "₹487", change: "+0.9%", up: true },
  { symbol: "NIFTY 50", price: "22,850", change: "+0.7%", up: true },
  { symbol: "SENSEX", price: "75,200", change: "+0.6%", up: true },
];

const features = [
  {
    icon: MessageSquare,
    color: "indigo",
    title: "Natural Language Queries",
    description: "Ask plain English questions and get instant financial insights. No complex filters or codes needed.",
    example: '"Show me 5-year ROCE trend for TCS"',
  },
  {
    icon: BarChart3,
    color: "teal",
    title: "Interactive Analytics",
    description: "Visualize revenue trends, margins, and returns with dynamic charts that adapt to your analysis.",
    example: '"Compare EBITDA margins across IT companies"',
  },
  {
    icon: Sparkles,
    color: "purple",
    title: "AI-Generated Reports",
    description: "One-click comprehensive reports with executive summaries, risk analysis, and investment perspectives.",
    example: '"Generate investment thesis for Reliance"',
  },
  {
    icon: GitCompareFeature,
    color: "orange",
    title: "Multi-Company Comparison",
    description: "Side-by-side comparison across 40+ financial parameters with visual winner/loser highlighting.",
    example: '"Compare HDFC vs Reliance vs TCS"',
  },
];

const steps = [
  { step: "01", title: "Search or Ask", desc: "Type a company name or ask a natural language question in the chat interface." },
  { step: "02", title: "Get Instant Analysis", desc: "AI processes XBRL-structured financial data and generates rich visual responses." },
  { step: "03", title: "Export & Share", desc: "Download PDF reports or share analysis links with your team or clients." },
];

// GitCompare icon workaround
function GitCompareFeature({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/>
      <path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/>
      <polyline points="15 9 18 6 21 9"/><polyline points="9 15 6 18 3 15"/>
    </svg>
  );
}

export default function LandingPage() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<CompanySuggestion[]>([]);
  const [companies, setCompanies] = useState<any[]>([]);
  const [tickerPos, setTickerPos] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const tickerRef = useRef<number | null>(null);

  // Fetch all companies on component mount
  useEffect(() => {
    const fetchCompanies = async () => {
      try {
        const data = await apiClient.getAllCompanies();
        setCompanies(data);
      } catch (error) {
        console.error("Failed to fetch companies:", error);
      }
    };

    fetchCompanies();
  }, []);

  useEffect(() => {
    let pos = 0;
    const animate = () => {
      pos -= 0.5;
      const width = tickerItems.length * 180;
      if (Math.abs(pos) > width) pos = 0;
      setTickerPos(pos);
      tickerRef.current = requestAnimationFrame(animate);
    };
    tickerRef.current = requestAnimationFrame(animate);
    return () => { if (tickerRef.current) cancelAnimationFrame(tickerRef.current); };
  }, []);

  const handleSearch = async (query: string) => {
    setSearchQuery(query);
    if (query.length > 1) {
      setIsSearching(true);
      try {
        const results = await apiClient.searchCompanies(query);
        setSearchResults(results);
      } catch (error) {
        console.error("Search failed:", error);
        setSearchResults([]);
      } finally {
        setIsSearching(false);
      }
    } else {
      setSearchResults([]);
    }
  };

  return (
    <div className="min-h-screen w-full overflow-x-hidden bg-white">
      {/* ── Header ─────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 bg-white/95 backdrop-blur-sm border-b border-gray-100 shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-3.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="size-9 rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center shadow-md shadow-indigo-200">
              <BarChart3 className="size-5 text-white" />
            </div>
            <div>
              <span className="text-gray-900 font-semibold">FinBot</span>
              <p className="text-xs text-gray-400 leading-none">Financial Intelligence Platform</p>
            </div>
          </div>

          <nav className="hidden md:flex items-center gap-1">
            <button onClick={() => navigate("/chat")} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-50 rounded-lg transition-colors">Chat</button>
            <button onClick={() => navigate("/compare")} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-50 rounded-lg transition-colors">Compare</button>
            <button onClick={() => navigate("/admin")} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-50 rounded-lg transition-colors">Admin</button>
            <Button
              size="sm"
              onClick={() => navigate("/chat")}
              className="ml-2 bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm shadow-indigo-200"
            >
              <Sparkles className="size-3.5 mr-1.5" />
              Launch App
            </Button>
          </nav>
        </div>
      </header>

      {/* ── Hero ────────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900 pt-20 pb-28">
        {/* Background decoration */}
        <div className="absolute inset-0 overflow-hidden">
          <div className="absolute top-20 right-20 size-96 bg-indigo-600/10 rounded-full blur-3xl" />
          <div className="absolute bottom-0 left-20 size-72 bg-purple-600/10 rounded-full blur-3xl" />
          <div
            className="absolute inset-0 opacity-5"
            style={{
              backgroundImage: `radial-gradient(circle at 1px 1px, rgba(255,255,255,0.3) 1px, transparent 0)`,
              backgroundSize: "32px 32px",
            }}
          />
        </div>

        <div className="relative max-w-7xl mx-auto px-6">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 text-indigo-300 mb-6 text-sm">
            <Sparkles className="size-3.5" />
            <span>AI-Powered • XBRL-Structured • Real-time Analysis</span>
          </div>

          <h1 className="text-5xl font-semibold text-white mb-5 leading-tight max-w-3xl">
            Your AI Financial Analyst
            <span className="block text-indigo-400">for Indian Equities</span>
          </h1>

          <p className="text-slate-400 mb-10 max-w-xl leading-relaxed">
            Chat naturally with financial data from Screener.in-grade XBRL filings.
            Compare companies, generate investment reports, and uncover insights — in seconds.
          </p>

          {/* Search */}
          <div className="relative max-w-2xl mb-8">
            <div className="relative flex items-center">
              <Search className="absolute left-4 size-5 text-slate-500 z-10" />
              <input
                type="text"
                placeholder="Search Reliance, TCS, HDFC Bank..."
                value={searchQuery}
                onChange={(e) => handleSearch(e.target.value)}
                className="w-full pl-12 pr-4 py-4 bg-white/10 border border-white/20 rounded-xl text-white placeholder-slate-500 outline-none focus:border-indigo-400 focus:bg-white/15 transition-all text-sm"
              />
              <button
                onClick={() => navigate("/chat")}
                className="absolute right-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm transition-colors"
              >
                Search
              </button>
            </div>

            {searchResults.length > 0 && (
              <div className="absolute top-full mt-2 w-full bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden z-20 max-h-80 overflow-y-auto">
                <div className="p-2 text-xs text-slate-400 border-b border-slate-700">
                  {searchResults.length} result{searchResults.length !== 1 ? 's' : ''} found
                </div>
                {searchResults.map((company) => (
                  <button
                    key={company.id}
                    onClick={() => navigate(`/company/${company.id}`)}
                    className="w-full px-4 py-3 text-left hover:bg-slate-800 transition-colors flex items-center justify-between border-b border-slate-800 last:border-b-0 group"
                  >
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-1">
                        <div className="text-white font-medium text-sm group-hover:text-indigo-300 transition-colors">{company.name}</div>
                        <div className="text-slate-300 text-sm font-medium">{company.symbol}</div>
                      </div>
                      <div className="flex items-center justify-between">
                        <div className="text-slate-400 text-xs">{company.scripcode}</div>
                        <div className="text-slate-500 text-xs">{company.sector}</div>
                      </div>
                    </div>
                    <ChevronRight className="size-4 text-slate-600 group-hover:text-indigo-400 transition-colors ml-3" />
                  </button>
                ))}
              </div>
            )}
            {searchQuery.length > 1 && searchResults.length === 0 && !isSearching && (
              <div className="absolute top-full mt-2 w-full bg-slate-900 border border-slate-700 rounded-xl shadow-2xl px-4 py-6 z-20 text-center">
                <p className="text-slate-400 text-sm">No companies found for "<span className="text-white font-medium">{searchQuery}</span>"</p>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            <Button
              size="lg"
              onClick={() => navigate("/chat")}
              className="bg-indigo-600 hover:bg-indigo-500 text-white px-6 shadow-lg shadow-indigo-900/50"
            >
              <MessageSquare className="size-4 mr-2" />
              Start AI Analysis
            </Button>
            <Button
              size="lg"
              variant="outline"
              onClick={() => navigate("/compare")}
              className="border-white/20 text-white hover:bg-white/10 bg-transparent"
            >
              Compare Companies
              <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>

          {/* Quick stats inline */}
          <div className="flex items-center gap-8 mt-12 text-sm text-slate-500">
            <div className="flex items-center gap-2">
              <Building2 className="size-4 text-indigo-400" />
              <span><span className="text-white font-medium">6</span> Companies Tracked</span>
            </div>
            <div className="flex items-center gap-2">
              <Database className="size-4 text-teal-400" />
              <span><span className="text-white font-medium">5 Years</span> Historical Data</span>
            </div>
            <div className="flex items-center gap-2">
              <Zap className="size-4 text-yellow-400" />
              <span><span className="text-white font-medium">40+</span> Financial Parameters</span>
            </div>
            <div className="flex items-center gap-2">
              <Shield className="size-4 text-green-400" />
              <span><span className="text-white font-medium">XBRL</span> Sourced Data</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── Ticker ──────────────────────────────────────────── */}
      <div className="bg-slate-950 border-y border-slate-800 py-3 overflow-hidden">
        <div
          className="flex items-center gap-0 whitespace-nowrap"
          style={{ transform: `translateX(${tickerPos}px)`, transition: "none" }}
        >
          {[...tickerItems, ...tickerItems, ...tickerItems].map((item, idx) => (
            <div
              key={idx}
              className="flex items-center gap-3 px-6 border-r border-slate-800"
              style={{ minWidth: 180 }}
            >
              <span className="text-slate-400 text-sm font-medium">{item.symbol}</span>
              <span className="text-white text-sm">{item.price}</span>
              <span className={`text-xs flex items-center gap-0.5 ${item.up ? "text-emerald-400" : "text-red-400"}`}>
                {item.up ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
                {item.change}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Features ────────────────────────────────────────── */}
      <section className="py-20 max-w-7xl mx-auto px-6">
        <div className="text-center mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-indigo-50 text-indigo-600 text-sm mb-4">
            <Sparkles className="size-3.5" />
            Platform Capabilities
          </div>
          <h2 className="text-3xl font-semibold text-gray-900 mb-3">
            Everything you need for equity analysis
          </h2>
          <p className="text-gray-500 max-w-lg mx-auto">
            Built for analysts, investors, and students who want instant, accurate, AI-assisted financial intelligence.
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
          {features.map((f, idx) => {
            const colorMap: Record<string, { bg: string; icon: string; border: string; chip: string }> = {
              indigo: { bg: "bg-indigo-50", icon: "text-indigo-600", border: "border-indigo-100 hover:border-indigo-200", chip: "bg-indigo-600/10 text-indigo-700" },
              teal: { bg: "bg-teal-50", icon: "text-teal-600", border: "border-teal-100 hover:border-teal-200", chip: "bg-teal-600/10 text-teal-700" },
              purple: { bg: "bg-purple-50", icon: "text-purple-600", border: "border-purple-100 hover:border-purple-200", chip: "bg-purple-600/10 text-purple-700" },
              orange: { bg: "bg-orange-50", icon: "text-orange-600", border: "border-orange-100 hover:border-orange-200", chip: "bg-orange-600/10 text-orange-700" },
            };
            const c = colorMap[f.color];
            return (
              <div key={idx} className={`group bg-white rounded-2xl p-6 border ${c.border} transition-all hover:shadow-lg cursor-pointer`}>
                <div className={`size-12 rounded-xl ${c.bg} flex items-center justify-center mb-4`}>
                  <f.icon className={`size-6 ${c.icon}`} />
                </div>
                <h3 className="text-gray-900 font-semibold mb-2">{f.title}</h3>
                <p className="text-gray-500 text-sm leading-relaxed mb-4">{f.description}</p>
                <div className={`text-xs px-3 py-1.5 rounded-lg ${c.chip} font-mono`}>
                  {f.example}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── How It Works ─────────────────────────────────────── */}
      <section className="py-20 bg-gradient-to-br from-slate-50 to-indigo-50/30">
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-semibold text-gray-900 mb-3">How it works</h2>
            <p className="text-gray-500">Three steps to powerful financial insights</p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            {steps.map((step, idx) => (
              <div key={idx} className="relative">
                {idx < steps.length - 1 && (
                  <div className="hidden md:block absolute top-8 left-full w-full h-px border-t-2 border-dashed border-indigo-200 z-0" />
                )}
                <div className="relative z-10 text-center">
                  <div className="size-16 rounded-2xl bg-white border-2 border-indigo-100 shadow-sm flex items-center justify-center mx-auto mb-5">
                    <span className="text-2xl font-semibold text-indigo-600">{step.step}</span>
                  </div>
                  <h3 className="text-gray-900 font-semibold mb-2">{step.title}</h3>
                  <p className="text-gray-500 text-sm leading-relaxed">{step.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Trending Companies ──────────────────────────────── */}
      <section className="py-20 max-w-7xl mx-auto px-6">
        <div className="flex items-center justify-between mb-10">
          <div>
            <h2 className="text-2xl font-semibold text-gray-900 mb-1">Tracked Companies</h2>
            <p className="text-gray-500 text-sm">Click any company to view detailed financial profile</p>
          </div>
          <Button
            variant="outline"
            onClick={() => navigate("/compare")}
            className="text-indigo-600 border-indigo-200 hover:bg-indigo-50"
          >
            Compare All
            <ArrowRight className="size-4 ml-2" />
          </Button>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {companies.map((company) => {
            // Safety check for financials data
            const hasFinancials = company.financials && company.financials.length >= 2;
            const latest = hasFinancials ? company.financials[0] : null;
            const prev = hasFinancials ? company.financials[1] : null;
            
            // Calculate growth if we have data, otherwise use defaults
            const salesGrowth = hasFinancials && prev.sales > 0 
              ? (((latest.sales - prev.sales) / prev.sales) * 100).toFixed(1) 
              : "0.0";
            const isUp = hasFinancials ? latest.sales > prev.sales : true;

            return (
              <button
                key={company.id}
                onClick={() => navigate(`/company/${company.id}`)}
                className="group bg-white rounded-2xl p-5 border border-gray-100 hover:border-indigo-200 hover:shadow-lg transition-all text-left"
              >
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <div className="font-semibold text-gray-900 group-hover:text-indigo-600 transition-colors">
                      {company.name}
                    </div>
                    <div className="text-sm text-gray-400 mt-0.5">{company.symbol} · {company.sector}</div>
                  </div>
                  {hasFinancials && (
                    <div className={`text-xs px-2.5 py-1 rounded-full font-medium ${isUp ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-600"}`}>
                      {isUp ? "+" : ""}{salesGrowth}% YoY
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <div className="text-xs text-gray-400 mb-0.5">Sales</div>
                    <div className="text-sm font-semibold text-gray-900">
                      {hasFinancials ? `₹${(latest.sales / 1000).toFixed(0)}B` : "N/A"}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 mb-0.5">OPM</div>
                    <div className="text-sm font-semibold text-gray-900">
                      {hasFinancials ? `${latest.opm}%` : "N/A"}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 mb-0.5">ROCE</div>
                    <div className="text-sm font-semibold text-gray-900">
                      {hasFinancials ? `${latest.roce}%` : "N/A"}
                    </div>
                  </div>
                </div>

                <div className="mt-3 flex items-center gap-1 text-xs text-indigo-600 opacity-0 group-hover:opacity-100 transition-opacity">
                  <span>View full profile</span>
                  <ChevronRight className="size-3.5" />
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────── */}
      <section className="py-20 mx-6 mb-6 rounded-3xl bg-gradient-to-br from-indigo-600 to-indigo-800 overflow-hidden relative">
        <div className="absolute inset-0 opacity-10" style={{ backgroundImage: "radial-gradient(circle at 2px 2px, white 1px, transparent 0)", backgroundSize: "32px 32px" }} />
        <div className="relative text-center px-6">
          <h2 className="text-3xl font-semibold text-white mb-3">Ready to start analyzing?</h2>
          <p className="text-indigo-200 mb-8 max-w-lg mx-auto">
            Join analysts and investors using FinBot to make smarter, faster investment decisions with AI.
          </p>
          <div className="flex items-center justify-center gap-3">
            <Button
              size="lg"
              onClick={() => navigate("/chat")}
              className="bg-white text-indigo-700 hover:bg-indigo-50 shadow-lg px-8"
            >
              <MessageSquare className="size-4 mr-2" />
              Start for Free
            </Button>
            <Button
              size="lg"
              variant="outline"
              onClick={() => navigate("/compare")}
              className="border-white/30 text-white hover:bg-white/10 bg-transparent"
            >
              Explore Companies
            </Button>
          </div>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────── */}
      <footer className="border-t bg-white px-6 py-8">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="size-8 rounded-lg bg-indigo-600 flex items-center justify-center">
              <BarChart3 className="size-4 text-white" />
            </div>
            <div>
              <div className="text-gray-900 font-semibold text-sm">FinBot</div>
              <div className="text-gray-400 text-xs">Financial Intelligence Platform</div>
            </div>
          </div>
          <div className="text-xs text-gray-400">
            © 2026 FinBot. Data sourced from XBRL filings. For educational & research purposes only.
          </div>
          <div className="flex items-center gap-6 text-sm text-gray-400">
            <a href="#" className="hover:text-gray-700 transition-colors">Privacy</a>
            <a href="#" className="hover:text-gray-700 transition-colors">Terms</a>
            <a href="#" className="hover:text-gray-700 transition-colors">Contact</a>
          </div>
        </div>
      </footer>
    </div>
  );
}