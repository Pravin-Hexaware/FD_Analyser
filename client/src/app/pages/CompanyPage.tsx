import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Download, MessageSquare, TrendingUp, TrendingDown,
  Building2, Hash, Users,
  BarChart3, PieChart as PieChartIcon, Activity, Target, Shield,
  DollarSign, Calendar, ExternalLink
} from "lucide-react";
import { Button } from "../components/ui/button";
import { apiClient } from "../../api/apiClient";
import { AppShell } from "../components/AppShell";
import {
  Area, LineChart, Line, BarChart, Bar, ComposedChart, ReferenceLine,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
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
  "Information Technology": "bg-indigo-100 text-indigo-700 border-indigo-200",
  "Healthcare": "bg-pink-100 text-pink-700 border-pink-200",
  "Manufacturing": "bg-yellow-100 text-yellow-700 border-yellow-200",
  "Communications Services": "bg-cyan-100 text-cyan-700 border-cyan-200",
};

interface IndianApiData {
  companyName: string;
  industry: string;
  companyProfile: {
    companyDescription: string;
    mgIndustry: string;
    isInId: string;
    exchangeCodeBse: string;
    exchangeCodeNse: string;
    peerCompanyList: Array<{
      tickerId: string;
      companyName: string;
      priceToBookValueRatio: number;
      priceToEarningsValueRatio: number;
      marketCap: number;
      price: number;
      percentChange: number;
      netChange: number;
      returnOnAverageEquity5YearAverage: number;
      returnOnAverageEquityTrailing12Month: number;
      ltDebtPerEquityMostRecentFiscalYear: number;
      netProfitMargin5YearAverage: number;
      netProfitMarginPercentTrailing12Month: number;
      dividendYieldIndicatedAnnualDividend: number;
      totalSharesOutstanding: number;
      languageSupport: string;
      imageUrl: string;
      overallRating: string;
      yhigh: number;
      ylow: number;
    }>;
  };
  currentPrice: {
    BSE: string;
    NSE: string;
  };
  recentNews: Array<{
    id: number;
    headline: string;
    date: string;
    timeToRead: number;
    url: string;
    summary: string;
  }>;
  analystView: Array<{
    colorCode: string;
    ratingName: string;
    ratingValue: number;
    numberOfAnalystsLatest: string;
  }>;
  recosBar: {
    stockAnalyst: Array<{
      colorCode: string;
      ratingName: string;
      ratingValue: number;
      minValue: number;
      maxValue: number;
      numberOfAnalysts: number;
    }>;
    tickerRatingValue: number;
    isDataPresent: boolean;
    noOfRecommendations: number;
    meanValue: number;
    tickerPercentage: number;
  };
  riskMeter: {
    categoryName: string;
    stdDev: number;
  };
  shareholding: Array<{
    categoryName: string;
    displayName: string;
    categories: Array<{
      holdingDate: string;
      percentage: string;
    }>;
  }>;
  stockTechnicalData: Array<{
    days: number;
    bsePrice: string;
    nsePrice: string;
  }>;
  stockDetailsReusableData: {
    marketCap: string;
    sectorPriceToEarningsValueRatio: string;
    dividendYieldIndicatedAnnualDividend?: string;
    pPerEBasicExcludingExtraordinaryItemsTTM?: string;
    NetIncome?: string;
    FiscalYear?: string;
    interimNetIncome?: string;
  };
  yearHigh: string;
  yearLow: string;
  percentChange: string;
  financials: Array<{
    stockFinancialMap: {
      INC: Array<{
        displayName: string;
        key: string;
        value: string;
      }>;
      BAL: Array<{
        displayName: string;
        key: string;
        value: string;
      }>;
      CAS: Array<{
        displayName: string;
        key: string;
        value: string;
      }>;
    };
    FiscalYear: string;
    EndDate: string;
    Type: string;
  }>;
}

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("Overview");
  const [company, setCompany] = useState<any>(null);
  const [indianApiData, setIndianApiData] = useState<IndianApiData | null>(null);
  const [annualData, setAnnualData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const tabs = [
    "Overview",
    "Technical",
    "Charts",
    "Financials",
    "Peers",
    "Analytics",
    "News"
  ];

  useEffect(() => {
    const loadCompanyData = async () => {
      if (!id) return;

      try {
        setLoading(true);
        setError(null);

        console.log(`[CompanyPage] Loading company: ${id}`);

        // Load company details
        const companyResponse = await apiClient.getCompanyDetails(id);
        let companyData = companyResponse.company;

        if (companyData) {
          console.log(`[CompanyPage] Found directly: id=${companyData.id}, symbol=${companyData.symbol}, name=${companyData.name}`);
        }

        // If direct lookup failed, try resolve/search fallback
        if (!companyData) {
          console.log(`[CompanyPage] Direct lookup failed, attempting fallback resolve...`);
          const fallbackCompanies = await apiClient.resolveCompany(id);
          if (fallbackCompanies.length > 0) {
            companyData = fallbackCompanies[0];
            console.log(`[CompanyPage] Resolved to: id=${companyData.id}, symbol=${companyData.symbol}, name=${companyData.name}`);
          }
        }

        if (!companyData) {
          setError("Company not found. Please search and try again.");
          setLoading(false);
          return;
        }

        setCompany(companyData);

        // Load company profile from external API via authenticated Indian API
        const indianApiKey = "sk-live-F9KJpcjUJEzJ20xknTJQ1FNW5pFbykjCiUdXTLnT";
        const profileName = companyData.symbol || companyData.bseCode || companyData.name;
        if (profileName) {
          try {
            console.log(`[IndianAPI] Fetching for: ${profileName}`);
            const profileResponse = await fetch(
              `https://stock.indianapi.in/stock?name=${encodeURIComponent(profileName)}`,
              {
                headers: {
                  "X-Api-Key": indianApiKey,
                },
              }
            );
            const profileData = await profileResponse.json();
            console.log(`[IndianAPI] Response for ${profileName}:`, profileData);
            if (profileResponse.ok && profileData) {
              setIndianApiData(profileData);
            }
          } catch (profileError) {
            console.warn("Failed to load company profile:", profileError);
          }
        }

        // Load annual financial data from local API
        try {
          const annualResponse = await fetch(`http://localhost:8001/api/companies/${companyData.id}/annual`);
          if (annualResponse.ok) {
            const annual = await annualResponse.json();
            setAnnualData(annual);
          }
        } catch (annualError) {
          console.warn("Failed to load annual financials:", annualError);
        }

      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to load company data";
        console.error("[CompanyPage] Error:", err);
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    loadCompanyData();
  }, [id]);

  if (loading) {
    return (
      <AppShell title="Loading...">
        <div className="flex items-center justify-center h-64">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mx-auto mb-4"></div>
            <div className="text-gray-400">Loading company data...</div>
          </div>
        </div>
      </AppShell>
    );
  }

  if (error || !company) {
    return (
      <AppShell title="Company Not Found">
        <div className="flex items-center justify-center h-64">
          <div className="text-center">
            <div className="text-gray-400 text-lg mb-3">
              {error || "Company not found"}
            </div>
            <Button onClick={() => navigate("/")} className="bg-indigo-600 hover:bg-indigo-700 text-white">
              Go Home
            </Button>
          </div>
        </div>
      </AppShell>
    );
  }

  // Extract data from Indian API
  const displayName = indianApiData?.companyName || company?.name || "Unknown Company";
  const displaySymbol = indianApiData?.companyProfile?.exchangeCodeNse || company?.symbol || "N/A";
  const bseCode = indianApiData?.companyProfile?.exchangeCodeBse || company?.bseCode || "N/A";
  const nseCode = indianApiData?.companyProfile?.exchangeCodeNse || company?.nseCode || "N/A";
  const currentPrice = indianApiData?.currentPrice?.BSE || indianApiData?.currentPrice?.NSE || "N/A";
  const percentChange = indianApiData?.percentChange || "N/A";
  const priceChange = indianApiData?.percentChange || "0";
  const marketCap = indianApiData?.stockDetailsReusableData?.marketCap || "N/A";
  const yearHigh = indianApiData?.yearHigh || "N/A";
  const yearLow = indianApiData?.yearLow || "N/A";
  const peRatio = indianApiData?.stockDetailsReusableData?.pPerEBasicExcludingExtraordinaryItemsTTM || "N/A";
  const sectorPe = indianApiData?.stockDetailsReusableData?.sectorPriceToEarningsValueRatio || "N/A";
  const dividendYield = indianApiData?.stockDetailsReusableData?.dividendYieldIndicatedAnnualDividend || "N/A";

  // Calculate EPS from financials if available
  const latestFinancial = indianApiData?.financials?.[0];
  const eps = latestFinancial?.stockFinancialMap?.INC?.find(item => item.key === "DilutedEPSExcludingExtraOrdItems")?.value || "N/A";

  // Technical data for charts
  const technicalData = indianApiData?.stockTechnicalData || [];
  const priceChartData = technicalData.map(item => ({
    days: `${item.days}D`,
    price: parseFloat(item.nsePrice || item.bsePrice || "0")
  }));

  const candleData = priceChartData.map((entry, idx) => {
    const base = entry.price;
    const volatility = (Math.sin(idx / 2) + 1) * 4;
    const open = Math.max(1, base - volatility * 0.6);
    const close = Math.max(1, base + volatility * 0.4);
    const high = Math.max(open, close) + volatility * 0.6;
    const low = Math.min(open, close) - volatility * 0.6;
    return {
      ticker: entry.days,
      open,
      close,
      high,
      low,
      volume: Math.floor(Math.random() * 150 + 50)
    };
  });

  // Simple market-depth simulation (buy/sell layers) for Overview.
  const marketDepth = {
    buy: [700, 950, 1200, 1600, 2100],
    sell: [620, 850, 1120, 1480, 1810]
  };
  const depthBuyTotal = marketDepth.buy.reduce((a, b) => a + b, 0);
  const depthSellTotal = marketDepth.sell.reduce((a, b) => a + b, 0);

  const latestAnnualRaw = annualData?.["Profit and Loss"] || null;
  const latestAnnual = indianApiData?.financials?.[0] || latestAnnualRaw || null;

  const getFinancialItem = (key: string) => {
    if (!latestAnnual?.stockFinancialMap?.INC) return "N/A";
    const found = latestAnnual.stockFinancialMap.INC.find((item: any) => item?.key === key);
    return found?.value ?? "N/A";
  };

  const getFinancialOrDefault = (key: string, defaultValue = "0") => {
    const item = getFinancialItem(key);
    return item === "N/A" ? defaultValue : item;
  };


  // Analyst ratings data
  const analystData = indianApiData?.analystView || [];

  // Shareholding data
  const shareholdingData = indianApiData?.shareholding?.[0]?.categories || [];

  // News data
  const newsData = indianApiData?.recentNews || [];

  // Peers data
  const peersData = indianApiData?.companyProfile?.peerCompanyList || [];

  const annual5Data = indianApiData?.financials?.slice(0, 5) || [];

  // const extractValue = (entry, path) => {
  //   if (!entry) return "N/A";
  //   const find = entry?.stockFinancialMap?.INC?.find((item) => item?.key === path);
  //   return find?.value || "N/A";
  // };

  const peerStats = {
    avgPE: peersData.length ? (peersData.reduce((sum, p) => sum + (Number(p.priceToEarningsValueRatio) || 0), 0) / peersData.length).toFixed(2) : "N/A",
    avgPB: peersData.length ? (peersData.reduce((sum, p) => sum + (Number(p.priceToBookValueRatio) || 0), 0) / peersData.length).toFixed(2) : "N/A",
    avgChange: peersData.length ? (peersData.reduce((sum, p) => sum + (Number(p.percentChange) || 0), 0) / peersData.length).toFixed(2) : "N/A",
  };

  const calcAnalyticsScore = () => {
    const opm = Number(getFinancialOrDefault("OPM_percentage", "0"));
    const roce = Number(getFinancialOrDefault("ROCE", "0"));
    if (!latestAnnual || (opm === 0 && roce === 0)) return "N/A";
    const closeToTarget = 100 - Math.min(40, Math.abs(opm - 30));
    return Math.min(100, Math.max(20, closeToTarget + roce)).toFixed(0);
  };

  const analyticsScore = calcAnalyticsScore();

  const sectorClass = SECTOR_COLORS[indianApiData?.industry || company?.sector] || "bg-gray-100 text-gray-700 border-gray-200";

  return (
    <AppShell
      breadcrumb={[
        { label: "Dashboard", href: "/" },
        { label: indianApiData?.industry || company?.sector || "Sector", href: "/" },
        { label: displaySymbol },
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
        <style>{`@keyframes ticker { 0% { transform: translateX(0%); } 100% { transform: translateX(-50%); }} .animate-ticker { animation: ticker 18s linear infinite; }`}</style>
        {/* Company Header */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 mb-6">
          <div className="flex items-start justify-between mb-6">
            <div className="flex items-start gap-4">
              <div className="size-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center shadow-md shadow-indigo-200 flex-shrink-0">
                <span className="text-white font-bold text-xl">{displaySymbol.charAt(0)}</span>
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-900 mb-2">{displayName}</h1>
                <div className="flex items-center gap-4 flex-wrap mb-3">
                  <div className="flex items-center gap-2">
                    <Hash className="size-4 text-gray-400" />
                    <span className="text-gray-600 font-medium">{displaySymbol}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Building2 className="size-4 text-gray-400" />
                    <span className="text-gray-600">BSE: {bseCode}</span>
                  </div>
                  <div className={`px-3 py-1 rounded-full text-xs font-medium ${sectorClass}`}>
                    {indianApiData?.industry || company?.sector}
                  </div>
                </div>
              </div>
            </div>
            <div className="text-right">
              <div className="text-3xl font-bold text-gray-900 mb-1">₹{currentPrice}</div>
              <div className={`text-sm font-medium flex items-center gap-1 ${parseFloat(priceChange) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {parseFloat(priceChange) >= 0 ? <TrendingUp className="size-4" /> : <TrendingDown className="size-4" />}
                {priceChange}%
              </div>
            </div>
          </div>

          {/* Key Metrics Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            <div className="text-center p-3 bg-gray-50 rounded-lg">
              <div className="text-xs text-gray-500 mb-1">Market Cap</div>
              <div className="text-sm font-semibold text-gray-900">₹{marketCap} Cr</div>
            </div>
            <div className="text-center p-3 bg-gray-50 rounded-lg">
              <div className="text-xs text-gray-500 mb-1">52W High</div>
              <div className="text-sm font-semibold text-gray-900">₹{yearHigh} Cr</div>
            </div>
            <div className="text-center p-3 bg-gray-50 rounded-lg">
              <div className="text-xs text-gray-500 mb-1">52W Low</div>
              <div className="text-sm font-semibold text-gray-900">₹{yearLow} Cr</div>
            </div>
            <div className="text-center p-3 bg-gray-50 rounded-lg">
              <div className="text-xs text-gray-500 mb-1">Percent Change</div>
              <div className="text-sm font-semibold text-gray-900">{percentChange}%</div>
            </div>
            <div className="text-center p-3 bg-gray-50 rounded-lg">
              <div className="text-xs text-gray-500 mb-1">Sector P/E</div>
              <div className="text-sm font-semibold text-gray-900">{sectorPe}</div>
            </div>
            <div className="text-center p-3 bg-gray-50 rounded-lg">
              <div className="text-xs text-gray-500 mb-1">EPS</div>
              <div className="text-sm font-semibold text-gray-900">₹{eps}</div>
            </div>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-1 mb-6 bg-white border border-gray-100 rounded-xl p-1.5 w-fit shadow-sm">
          {tabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                activeTab === tab
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-gray-600 hover:text-gray-900 hover:bg-gray-50"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        {activeTab === "Overview" && (
          <div className="space-y-6">
            {/* Dividend Yield & Risk Meter */}
            <div className="grid md:grid-cols-2 gap-6">
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <div className="flex items-center gap-3 mb-4">
                  <DollarSign className="size-5 text-green-600" />
                  <h3 className="text-lg font-semibold text-gray-900">Dividend Yield</h3>
                </div>
                <div className="text-3xl font-bold text-green-600 mb-2">{dividendYield}%</div>
                <p className="text-gray-600 text-sm">Annual dividend yield based on current price</p>
              </div>

              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <div className="flex items-center gap-3 mb-4">
                  <Shield className="size-5 text-orange-600" />
                  <h3 className="text-lg font-semibold text-gray-900">Risk Meter</h3>
                </div>
                <div className="text-3xl font-bold text-orange-600 mb-2">
                  {indianApiData?.riskMeter?.categoryName || "N/A"}
                </div>
                <div className="text-sm text-gray-600">
                  Std Dev: {indianApiData?.riskMeter?.stdDev?.toFixed(2) || "N/A"}
                </div>
              </div>
            </div>

            {/* Market Depth Layers */}
            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <div className="flex items-center gap-3 mb-6">
                <span className="text-xl font-semibold">Market Depth</span>
                <span className="text-xs text-gray-500">Buy / Sell layers</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
                <div className="text-sm text-slate-600">Buy Layers</div>
                <div className="text-sm text-slate-600">Sell Layers</div>
              </div>
              <div className="space-y-2">
                {marketDepth.buy.map((b, i) => {
                  const s = marketDepth.sell[i];
                  const total = Math.max(depthBuyTotal, depthSellTotal, 1);
                  return (
                    <div key={i} className="flex items-center gap-2">
                      <div className="w-1/2 h-2 rounded bg-green-200" style={{ width: `${(b / total) * 100}%` }} />
                      <div className="w-1/2 h-2 rounded bg-red-200" style={{ width: `${(s / total) * 100}%` }} />
                    </div>
                  );
                })}
              </div>
              <div className="mt-2 text-xs text-gray-500">Total Buy ${depthBuyTotal.toLocaleString()} · Total Sell ${depthSellTotal.toLocaleString()}</div>
            </div>

            {/* Shareholding Pattern */}
            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <div className="flex items-center gap-3 mb-6">
                <PieChartIcon className="size-5 text-indigo-600" />
                <h3 className="text-lg font-semibold text-gray-900">Shareholding Pattern</h3>
              </div>
              <div className="grid md:grid-cols-3 gap-4">
                {shareholdingData.map((item, index) => (
                  <div key={index} className="text-center">
                    <div className="text-2xl font-bold text-gray-900 mb-1">{item.percentage}%</div>
                    <div className="text-sm text-gray-600">{item.holdingDate}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {activeTab === "Technical" && (
          <div className="space-y-6">
            {/* Moving Averages */}
            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <div className="flex items-center gap-3 mb-6">
                <Activity className="size-5 text-blue-600" />
                <h3 className="text-lg font-semibold text-gray-900">Moving Averages</h3>
              </div>
              <div className="grid md:grid-cols-3 gap-4">
                {technicalData.slice(0, 3).map((item, index) => (
                  <div key={index} className="text-center p-4 bg-gray-50 rounded-lg">
                    <div className="text-sm text-gray-500 mb-1">{item.days} Days</div>
                    <div className="text-lg font-semibold text-gray-900">₹{item.nsePrice || item.bsePrice}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Trend Indicators */}
            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <div className="flex items-center gap-3 mb-6">
                <Target className="size-5 text-purple-600" />
                <h3 className="text-lg font-semibold text-gray-900">Trend Indicators</h3>
              </div>
              <div className="grid md:grid-cols-2 gap-6">
                <div className="text-center">
                  <div className="text-4xl font-bold text-green-600 mb-2">↗️</div>
                  <div className="text-sm text-gray-600">Price Trend</div>
                  <div className="text-lg font-semibold text-green-600">Bullish</div>
                </div>
                <div className="text-center">
                  <div className="text-4xl font-bold text-blue-600 mb-2">📊</div>
                  <div className="text-sm text-gray-600">Volume</div>
                  <div className="text-lg font-semibold text-blue-600">Moderate</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "Charts" && (
          <div className="space-y-6">
            {/* Candle + Volume */}
            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div className="flex items-center gap-3">
                  <BarChart3 className="size-5 text-indigo-600" />
                  <h3 className="text-lg font-semibold text-gray-900">Candlestick + Volume</h3>
                </div>
                <small className="text-xs text-gray-500">Sample OHLC data</small>
              </div>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={candleData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="ticker" />
                    <YAxis domain={["dataMin - 5", "dataMax + 5"]} />
                    <Tooltip formatter={(value, name) => [typeof value === "number" ? value.toFixed(2) : value, name]} />
                    <ReferenceLine y={Number(currentPrice) || 0} stroke="#f59e0b" strokeDasharray="3 3" />
                    <Bar dataKey="low" fill="#10B981" barSize={2} />
                    <Bar dataKey="high" fill="#ef4444" barSize={2} />
                    <Line type="monotone" dataKey="close" stroke="#4F46E5" strokeWidth={2} dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Price Chart */}
            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <div className="flex items-center gap-3 mb-6">
                <BarChart3 className="size-5 text-indigo-600" />
                <h3 className="text-lg font-semibold text-gray-900">Price Trend</h3>
              </div>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={priceChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="days" />
                    <YAxis />
                    <Tooltip formatter={(value) => [`₹${value}`, "Price"]} />
                    <Line type="monotone" dataKey="price" stroke="#4F46E5" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Volume Chart */}
            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <div className="flex items-center gap-3 mb-6">
                <BarChart3 className="size-5 text-green-600" />
                <h3 className="text-lg font-semibold text-gray-900">Volume History</h3>
              </div>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={candleData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="ticker" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="volume" fill="#10B981" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}

        {activeTab === "Financials" && (
          <div className="space-y-6">
            {/* <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-xs text-gray-500">Revenue (latest available)</p>
                <p className="text-3xl font-bold text-indigo-600">₹{latestAnnual?.Sales ? (latestAnnual.Sales / 100).toLocaleString() : "N/A"} Cr</p>
                <p className="text-gray-500 text-sm">{latestAnnual?.FiscalYear || "N/A"}</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-xs text-gray-500">EBITDA</p>
                <p className="text-3xl font-bold text-green-600">₹{latestAnnual?.EBITDA ? (latestAnnual.EBITDA / 100).toLocaleString() : "N/A"} Cr</p>
                <p className="text-gray-500 text-sm">Growth vs Prev: {latestAnnual?.EBITDA_growth || "N/A"}%</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-xs text-gray-500">Net Profit</p>
                <p className="text-3xl font-bold text-orange-600">₹{latestAnnual?.NetProfit ? (latestAnnual.NetProfit / 100).toLocaleString() : "N/A"} Cr</p>
                <p className="text-gray-500 text-sm">Margin: {latestAnnual?.NetProfit_margin || "N/A"}%</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-xs text-gray-500">ROCE</p>
                <p className="text-2xl font-bold text-indigo-600">{getFinancialOrDefault("ROCE", "N/A")}%</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-xs text-gray-500">OPM</p>
                <p className="text-2xl font-bold text-green-600">{getFinancialOrDefault("OPM_percentage", "N/A")}%</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-xs text-gray-500">D/E Ratio</p>
                <p className="text-2xl font-bold text-teal-600">{getFinancialOrDefault("DE_ratio", "N/A")}x</p>
              </div>
            </div> */}

            {/* Comprehensive Financial Statements Table */}
            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <div className="flex items-center gap-3 mb-6">
                <BarChart3 className="size-5 text-blue-600" />
                <h3 className="text-lg font-semibold text-gray-900">Comprehensive Financial Statements (in Cr)</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b-2 border-gray-300 bg-gradient-to-r from-slate-100 to-slate-50">
                      <th className="text-left py-3 px-3 font-bold text-gray-800 w-48 sticky left-0 bg-gradient-to-r from-slate-100 to-slate-50">Metric</th>
                      {indianApiData?.financials?.slice(0, 5).map((item, idx) => (
                        <th key={idx} className="text-right py-3 px-2 font-bold text-gray-800 min-w-24">
                          FY {item.FiscalYear}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {/* Income Statement Section */}
                    <tr className="bg-blue-50 border-b border-gray-200">
                      <td colSpan={6} className="py-2 px-3 font-bold text-blue-900 text-sm">
                        INCOME STATEMENT
                      </td>
                    </tr>
                    {(() => {
                      const incMetrics = indianApiData?.financials?.[0]?.stockFinancialMap?.INC || [];
                      return incMetrics.slice(0, 15).map((metric, idx) => (
                        <tr key={`inc-${idx}`} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="py-2 px-3 text-gray-900 font-medium sticky left-0 bg-white">{metric.displayName}</td>
                          {indianApiData?.financials?.slice(0, 5).map((yearData, yIdx) => {
                            const value = yearData.stockFinancialMap.INC.find(item => item.key === metric.key)?.value || "N/A";
                            return (
                              <td key={`inc-${idx}-${yIdx}`} className="py-2 px-2 text-right text-gray-800">
                                {value !== "N/A" ? (isNaN(parseFloat(value)) ? value : parseFloat(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })) : "-"}
                              </td>
                            );
                          })}
                        </tr>
                      ));
                    })()}
                    <tr className="bg-whitw-50 border-b border-gray-200">
                      <td colSpan={6} className="py-2 px-3 font-bold text-sm">
                
                      </td>
                    </tr>

                    {/* Balance Sheet Section */}
                    <tr className="bg-green-50 border-b border-gray-200">
                      <td colSpan={6} className="py-2 px-3 font-bold text-green-900 text-sm">
                        BALANCE SHEET
                      </td>
                    </tr>
                    {(() => {
                      const balMetrics = indianApiData?.financials?.[0]?.stockFinancialMap?.BAL || [];
                      return balMetrics.slice(0, 15).map((metric, idx) => (
                        <tr key={`bal-${idx}`} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="py-2 px-3 text-gray-900 font-medium sticky left-0 bg-white">{metric.displayName}</td>
                          {indianApiData?.financials?.slice(0, 5).map((yearData, yIdx) => {
                            const value = yearData.stockFinancialMap.BAL.find(item => item.key === metric.key)?.value || "N/A";
                            return (
                              <td key={`bal-${idx}-${yIdx}`} className="py-2 px-2 text-right text-gray-800">
                                {value !== "N/A" ? (isNaN(parseFloat(value)) ? value : parseFloat(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })) : "-"}
                              </td>
                            );
                          })}
                        </tr>
                      ));
                    })()}
                    <tr className="bg-whitw-50 border-b border-gray-200">
                      <td colSpan={6} className="py-2 px-3 font-bold text-sm">
                
                      </td>
                    </tr>

                    {/* Cash Flow Statement Section */}
                    <tr className="bg-purple-50 border-b border-gray-200">
                      <td colSpan={6} className="py-2 px-3 font-bold text-purple-900 text-sm">
                        CASH FLOW STATEMENT
                      </td>
                    </tr>
                    {(() => {
                      const casMetrics = indianApiData?.financials?.[0]?.stockFinancialMap?.CAS || [];
                      return casMetrics.slice(0, 15).map((metric, idx) => (
                        <tr key={`cas-${idx}`} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="py-2 px-3 text-gray-900 font-medium sticky left-0 bg-white">{metric.displayName}</td>
                          {indianApiData?.financials?.slice(0, 5).map((yearData, yIdx) => {
                            const value = yearData.stockFinancialMap.CAS.find(item => item.key === metric.key)?.value || "N/A";
                            return (
                              <td key={`cas-${idx}-${yIdx}`} className="py-2 px-2 text-right text-gray-800">
                                {value !== "N/A" ? (isNaN(parseFloat(value)) ? value : parseFloat(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })) : "-"}
                              </td>
                            );
                          })}
                        </tr>
                      ));
                    })()}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-gray-500 mt-4">All values are in Crores (Cr). Data is organized by Financial Statement sections: Income Statement, Balance Sheet, and Cash Flow.</p>
            </div>
          </div>
        )}

        {activeTab === "Peers" && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-xs text-gray-500">Peer count</p>
                <p className="text-3xl font-bold text-indigo-600">{peersData.length}</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-xs text-gray-500">Avg P/E</p>
                <p className="text-3xl font-bold text-green-600">{peerStats.avgPE}</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-xs text-gray-500">Avg P/B</p>
                <p className="text-3xl font-bold text-indigo-600">{peerStats.avgPB}</p>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <div className="flex items-center gap-3 mb-6">
                <Users className="size-5 text-indigo-600" />
                <h3 className="text-lg font-semibold text-gray-900">Peer Comparison Matrix</h3>
              </div>
              {peersData.length === 0 ? (
                <p className="text-sm text-gray-500">No peer data available.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-200 bg-slate-50">
                        <th className="text-left py-3 font-medium text-gray-700">Metric</th>
                        {peersData.map((peer, idx) => (
                          <th key={idx} className="text-right py-3 font-medium text-gray-700">{peer.companyName}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        { label: 'Price', key: 'price' },
                        { label: 'Change %', key: 'percentChange' },
                        { label: 'Mkt Cap (Cr)', key: 'marketCap' },
                        { label: 'Price to Earnings', key: 'priceToEarningsValueRatio' },
                        { label: 'Price to Book', key: 'priceToBookValueRatio' },
                        { label: 'ROE 5Y', key: 'returnOnAverageEquity5YearAverage' },
                        { label: 'ROE TTM', key: 'returnOnAverageEquityTrailing12Month' },
                        { label: 'Debt/Equity', key: 'ltDebtPerEquityMostRecentFiscalYear' },
                        { label: 'Net Profit 5Y', key: 'netProfitMargin5YearAverage' },
                        { label: 'Net Profit TTM', key: 'netProfitMarginPercentTrailing12Month' },
                        { label: 'Dividend Yield', key: 'dividendYieldIndicatedAnnualDividend' },
                        { label: 'YearHigh', key:'yhigh'},
                        { label: 'YearLow', key:'ylow'}
                      ].map((metric) => (
                        <tr key={metric.key} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="py-3 text-gray-900 font-medium">{metric.label}</td>
                          {peersData.map((peer, index) => (
                            <td key={index} className="py-3 text-right text-gray-900">{peer[metric.key] ?? 'N/A'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === "Analytics" && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-sm text-gray-500">Profitability (ROCE)</p>
                <p className="text-3xl font-bold text-indigo-600">{latestAnnual?.ROCE ?? "N/A"}%</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-sm text-gray-500">Operating Margin (OPM)</p>
                <p className="text-3xl font-bold text-green-600">{latestAnnual?.OPM_percentage ?? "N/A"}%</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <p className="text-sm text-gray-500">Leverage (D/E)</p>
                <p className="text-3xl font-bold text-teal-600">{latestAnnual?.DE_ratio ?? "N/A"}x</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Analytics Score</h3>
                <div className="flex items-center justify-between">
                  <span className="text-4xl font-bold text-indigo-700">{analyticsScore}</span>
                  <span className="text-xs text-gray-500">Higher is better (0-100)</span>
                </div>
                <div className="mt-3 h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div style={{ width: `${analyticsScore === "N/A" ? 0 : Number(analyticsScore)}%` }} className="h-full bg-gradient-to-r from-indigo-500 to-green-500" />
                </div>
              </div>

              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Peer Stats</h3>
                <ul className="space-y-2 text-sm text-gray-700">
                  <li>Avg P/E: <strong>{peerStats.avgPE}</strong></li>
                  <li>Avg P/B: <strong>{peerStats.avgPB}</strong></li>
                  <li>Avg Change: <strong>{peerStats.avgChange}%</strong></li>
                  <li>Peers: <strong>{peersData.length}</strong></li>
                </ul>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Analyst sentiment</h3>
              {analystData.length === 0 ? (
                <p className="text-sm text-gray-500">No analyst ratings available.</p>
              ) : (
                <dl className="grid grid-cols-1 gap-2 text-sm text-gray-700">
                  {analystData.slice(0, 5).map((item, idx) => (
                    <div key={idx} className="flex items-center justify-between">
                      <span>{item.ratingName}</span>
                      <strong>{item.ratingValue}%</strong>
                    </div>
                  ))}
                </dl>
              )}
            </div>

            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Detailed Analytics Data</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm text-gray-700">
                <div>Revenue Growth: <strong>{latestAnnual?.SalesGrowth || "N/A"}%</strong></div>
                <div>Net Profit Growth: <strong>{latestAnnual?.NetProfitGrowth || "N/A"}%</strong></div>
                <div>CFO/PAT: <strong>{latestAnnual?.CFO_over_PAT || "N/A"}</strong></div>
                <div>Debt coverage: <strong>{latestAnnual?.Debt_coverage || "N/A"}</strong></div>
                <div>Return on Equity: <strong>{latestAnnual?.ROE || "N/A"}%</strong></div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "News" && (
          <div className="space-y-4">
            {newsData.map((news, index) => (
              <div key={index} className="bg-white rounded-xl border border-gray-100 p-6 hover:shadow-md transition-shadow">
                <div className="flex items-start justify-between mb-3">
                  <h4 className="text-lg font-semibold text-gray-900 flex-1 mr-4">{news.headline}</h4>
                  <div className="flex items-center gap-2 text-sm text-gray-500">
                    <Calendar className="size-4" />
                    {news.date}
                  </div>
                </div>
                <p className="text-gray-600 mb-4">{news.summary}</p>
                <div className="flex items-center justify-between">
                  <div className="text-sm text-gray-500">
                    {news.timeToRead} min read
                  </div>
                  <Button variant="outline" size="sm" asChild>
                    <a href={news.url} target="_blank" rel="noopener noreferrer">
                      Read More <ExternalLink className="size-3 ml-1" />
                    </a>
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Sticky floating mini indicators */}
      <div className="fixed right-5 bottom-5 z-50 space-y-2">
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 shadow-lg w-52">
          <div className="text-xs text-gray-500">F&O</div>
          <div className="font-semibold text-gray-900">{Number(priceChange) > 0 ? "Bullish" : "Bearish"}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 shadow-lg w-52">
          <div className="text-xs text-gray-500">Strength</div>
          <div className="font-semibold text-green-600">{Number(priceChange) > 1 ? "Strong" : "Neutral"}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 shadow-lg w-52">
          <div className="text-xs text-gray-500">Weakness</div>
          <div className="font-semibold text-red-600">{Number(priceChange) < -1 ? "High" : "Low"}</div>
        </div>
      </div>

    </AppShell>
  );
}
