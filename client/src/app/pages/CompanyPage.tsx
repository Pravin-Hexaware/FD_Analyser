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
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, RadialBarChart, RadialBar, Legend, Cell,
  PieChart, Pie, AreaChart, ScatterChart, Scatter
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
    if (!indianApiData?.analystView) return "N/A";

    let totalWeighted = 0;
    let totalAnalysts = 0;

    const ratingWeights = {
      "Strong Buy": 1,
      "Buy": 2,
      "Hold": 3,
      "Sell": 4,
      "Strong Sell": 5
    };

    indianApiData.analystView.forEach(item => {
      if (item.ratingName !== "Total") {
        const weight = ratingWeights[item.ratingName as keyof typeof ratingWeights] || 3;
        const num = Number(item.numberOfAnalystsLatest) || 0;
        totalWeighted += num * weight;
        totalAnalysts += num;
      }
    });

    if (totalAnalysts === 0) return "N/A";

    const averageRating = totalWeighted / totalAnalysts;
    // Score = (6 - averageRating) * 20, clamped to 0-100
    const score = Math.max(0, Math.min(100, (6 - averageRating) * 20));
    return score.toFixed(0);
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
            {/* Key Financial Metrics */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-sm text-gray-600 mb-1">Dividend Yield</div>
                <div className="text-xl font-semibold text-green-600">{dividendYield}%</div>
                <div className="text-xs text-gray-500 mt-1">Annual yield</div>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-sm text-gray-600 mb-1">Risk Category</div>
                <div className="text-xl font-semibold text-orange-600">{indianApiData?.riskMeter?.categoryName || "N/A"}</div>
                <div className="text-xs text-gray-500 mt-1">Market risk level</div>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-sm text-gray-600 mb-1">Volatility</div>
                <div className="text-xl font-semibold text-gray-900">{indianApiData?.riskMeter?.stdDev?.toFixed(2) || "N/A"}%</div>
                <div className="text-xs text-gray-500 mt-1">Std deviation</div>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-sm text-gray-600 mb-1">52W Range</div>
                <div className="text-sm font-semibold text-gray-900">₹{yearLow} - ₹{yearHigh}</div>
                <div className="text-xs text-gray-500 mt-1">Price range</div>
              </div>
            </div>

            {/* Shareholding Pattern */}
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-6">Shareholding Pattern</h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={shareholdingData.map(item => ({
                    date: item.holdingDate,
                    percentage: Number(item.percentage)
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" />
                    <YAxis domain={[0, 'dataMax + 5']} />
                    <Tooltip formatter={(value) => [`${value}%`, 'Shareholding']} />
                    <Line
                      type="monotone"
                      dataKey="percentage"
                      stroke="#4F46E5"
                      strokeWidth={2}
                      dot={{ fill: '#4F46E5', strokeWidth: 2, r: 4 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                {shareholdingData.slice(0, 3).map((item, index) => (
                  <div key={index} className="text-center p-3 bg-gray-50 rounded-lg">
                    <div className="text-sm text-gray-600">{item.holdingDate}</div>
                    <div className="text-lg font-semibold text-gray-900">{item.percentage}%</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Market Sentiment */}
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-6 flex items-center gap-2">
                <PieChartIcon className="size-5 text-indigo-600" />
                Market Sentiment Analysis
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={[
                          { name: 'Buy Pressure', value: depthBuyTotal, fill: '#10B981' },
                          { name: 'Sell Pressure', value: depthSellTotal, fill: '#EF4444' }
                        ]}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={100}
                        paddingAngle={5}
                        dataKey="value"
                      >
                        <Cell fill="#10B981" />
                        <Cell fill="#EF4444" />
                      </Pie>
                      <Tooltip formatter={(value) => [`${value.toLocaleString()}`, 'Volume']} />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="space-y-4">
                  <div className="flex items-center justify-between p-4 bg-green-50 rounded-lg border border-green-200 hover:shadow-md transition-shadow cursor-pointer">
                    <div className="flex items-center gap-3">
                      <div className="size-3 bg-green-500 rounded-full"></div>
                      <div>
                        <div className="font-semibold text-green-700">Buy Pressure</div>
                        <div className="text-sm text-green-600">{depthBuyTotal.toLocaleString()}</div>
                      </div>
                    </div>
                    <TrendingUp className="size-5 text-green-500" />
                  </div>
                  <div className="flex items-center justify-between p-4 bg-red-50 rounded-lg border border-red-200 hover:shadow-md transition-shadow cursor-pointer">
                    <div className="flex items-center gap-3">
                      <div className="size-3 bg-red-500 rounded-full"></div>
                      <div>
                        <div className="font-semibold text-red-700">Sell Pressure</div>
                        <div className="text-sm text-red-600">{depthSellTotal.toLocaleString()}</div>
                      </div>
                    </div>
                    <TrendingDown className="size-5 text-red-500" />
                  </div>
                  <div className="text-center p-3 bg-gray-50 rounded-lg border">
                    <div className="text-sm text-gray-600">Market Balance</div>
                    <div className={`text-lg font-semibold ${depthBuyTotal > depthSellTotal ? 'text-green-600' : depthSellTotal > depthBuyTotal ? 'text-red-600' : 'text-gray-600'}`}>
                      {depthBuyTotal > depthSellTotal ? 'Bullish' : depthSellTotal > depthBuyTotal ? 'Bearish' : 'Neutral'}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Technical Indicators */}
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-6 flex items-center gap-2">
                <Activity className="size-5 text-indigo-600" />
                Technical Analysis
              </h3>
              <div className="h-64 mb-6">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={technicalData.slice(0, 5).map((item, index) => ({
                    period: `${item.days}D`,
                    price: parseFloat(item.nsePrice || item.bsePrice || "0"),
                    volume: Math.floor(Math.random() * 100 + 50) // Simulated volume
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="period" />
                    <YAxis />
                    <Tooltip formatter={(value, name) => [name === 'price' ? `₹${value}` : value, name === 'price' ? 'Price' : 'Volume']} />
                    <Bar dataKey="price" fill="#4F46E5" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="flex items-center justify-between p-4 bg-gradient-to-r from-green-50 to-green-100 rounded-lg border border-green-200 hover:shadow-md transition-shadow cursor-pointer">
                  <div className="flex items-center gap-3">
                    <div className="size-8 bg-green-500 rounded-full flex items-center justify-center">
                      <TrendingUp className="size-4 text-white" />
                    </div>
                    <div>
                      <div className="font-semibold text-green-700">Bullish Signal</div>
                      <div className="text-sm text-green-600">Price momentum positive</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold text-green-600">+2.4%</div>
                    <div className="text-xs text-green-500">vs yesterday</div>
                  </div>
                </div>
                <div className="flex items-center justify-between p-4 bg-gradient-to-r from-blue-50 to-blue-100 rounded-lg border border-blue-200 hover:shadow-md transition-shadow cursor-pointer">
                  <div className="flex items-center gap-3">
                    <div className="size-8 bg-blue-500 rounded-full flex items-center justify-center">
                      <Activity className="size-4 text-white" />
                    </div>
                    <div>
                      <div className="font-semibold text-blue-700">Volume Analysis</div>
                      <div className="text-sm text-blue-600">Trading activity</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold text-blue-600">Moderate</div>
                    <div className="text-xs text-blue-500">avg volume</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "Charts" && (
          <div className="space-y-6">
            {/* Price Trend with Area Chart */}
            <div className="bg-white rounded-xl border border-gray-100 p-6">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div className="flex items-center gap-3">
                  <TrendingUp className="size-5 text-indigo-600" />
                  <h3 className="text-lg font-semibold text-gray-900">Price Trend Analysis</h3>
                </div>
                <div className="flex items-center gap-2 text-sm text-gray-600">
                  <div className="size-2 bg-indigo-500 rounded-full"></div>
                  <span>Current: ₹{currentPrice}</span>
                </div>
              </div>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={priceChartData}>
                    <defs>
                      <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#4F46E5" stopOpacity={0.3}/>
                        <stop offset="95%" stopColor="#4F46E5" stopOpacity={0.1}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="days" />
                    <YAxis />
                    <Tooltip formatter={(value) => [`₹${value}`, "Price"]} />
                    <Area type="monotone" dataKey="price" stroke="#4F46E5" fillOpacity={1} fill="url(#priceGradient)" strokeWidth={2} />
                    <ReferenceLine y={Number(currentPrice) || 0} stroke="#f59e0b" strokeDasharray="5 5" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Volume Distribution Pie Chart */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <div className="flex items-center gap-3 mb-6">
                  <PieChartIcon className="size-5 text-green-600" />
                  <h3 className="text-lg font-semibold text-gray-900">Volume Distribution</h3>
                </div>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={candleData.slice(0, 4).map((item, index) => ({
                          name: item.ticker,
                          value: item.volume,
                          fill: ['#10B981', '#3B82F6', '#F59E0B', '#EF4444'][index % 4]
                        }))}
                        cx="50%"
                        cy="50%"
                        innerRadius={40}
                        outerRadius={80}
                        paddingAngle={5}
                        dataKey="value"
                      >
                        {candleData.slice(0, 4).map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={['#10B981', '#3B82F6', '#F59E0B', '#EF4444'][index % 4]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(value) => [value, 'Volume']} />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Scatter Plot for Price vs Volume */}
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <div className="flex items-center gap-3 mb-6">
                  <Activity className="size-5 text-purple-600" />
                  <h3 className="text-lg font-semibold text-gray-900">Price vs Volume Correlation</h3>
                </div>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <ScatterChart data={candleData.map(item => ({
                      price: item.close,
                      volume: item.volume,
                      period: item.ticker
                    }))}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="price" name="Price" />
                      <YAxis dataKey="volume" name="Volume" />
                      <Tooltip cursor={{ strokeDasharray: '3 3' }} />
                      <Scatter name="Price-Volume" dataKey="volume" fill="#8B5CF6" />
                    </ScatterChart>
                  </ResponsiveContainer>
                </div>
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
                    <Bar dataKey="volume" fill="#10B981" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}

        {activeTab === "Financials" && (
          <div className="space-y-6">
            {/* Key Financial Metrics Charts */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <div className="flex items-center gap-3 mb-6">
                  <DollarSign className="size-5 text-green-600" />
                  <h3 className="text-lg font-semibold text-gray-900">Revenue Trend</h3>
                </div>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={annual5Data.map(item => {
                      const revenue = item.stockFinancialMap?.INC?.find(m => m.key === 'TotalRevenue')?.value;
                      return {
                        year: item.FiscalYear,
                        revenue: revenue ? parseFloat(revenue) : 0
                      };
                    })}>
                      <defs>
                        <linearGradient id="revenueGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#10B981" stopOpacity={0.3}/>
                          <stop offset="95%" stopColor="#10B981" stopOpacity={0.1}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="year" />
                      <YAxis />
                      <Tooltip formatter={(value) => [`₹${value} Cr`, "Revenue"]} />
                      <Area type="monotone" dataKey="revenue" stroke="#10B981" fillOpacity={1} fill="url(#revenueGradient)" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <div className="flex items-center gap-3 mb-6">
                  <Target className="size-5 text-blue-600" />
                  <h3 className="text-lg font-semibold text-gray-900">Profitability Metrics</h3>
                </div>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={annual5Data.map(item => {
                      const netIncome = item.stockFinancialMap?.INC?.find(m => m.key === 'NetIncome')?.value;
                      const totalRevenue = item.stockFinancialMap?.INC?.find(m => m.key === 'TotalRevenue')?.value;
                      const margin = totalRevenue && netIncome ? (parseFloat(netIncome) / parseFloat(totalRevenue)) * 100 : 0;
                      return {
                        year: item.FiscalYear,
                        margin: margin
                      };
                    })}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="year" />
                      <YAxis />
                      <Tooltip formatter={(value) => [`${value.toFixed(1)}%`, "Net Margin"]} />
                      <Bar dataKey="margin" fill="#3B82F6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

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
                <BarChart3 className="size-5 text-indigo-600" />
                <h3 className="text-lg font-semibold text-gray-900">Peer Performance Comparison</h3>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={peersData.slice(0, 5).map(peer => ({
                    name: peer.companyName.substring(0, 10) + (peer.companyName.length > 10 ? '...' : ''),
                    pe: parseFloat(peer.priceToEarningsValueRatio) || 0,
                    change: parseFloat(peer.percentChange) || 0
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="pe" fill="#4F46E5" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
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
            {/* Key Metrics Overview */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-sm text-gray-600 mb-1">ROCE</div>
                <div className="text-xl font-semibold text-gray-900">{latestAnnual?.ROCE ?? "N/A"}%</div>
                <div className="text-xs text-gray-500 mt-1">Profitability</div>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-sm text-gray-600 mb-1">OPM</div>
                <div className="text-xl font-semibold text-gray-900">{latestAnnual?.OPM_percentage ?? "N/A"}%</div>
                <div className="text-xs text-gray-500 mt-1">Operating Margin</div>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-sm text-gray-600 mb-1">D/E Ratio</div>
                <div className="text-xl font-semibold text-gray-900">{latestAnnual?.DE_ratio ?? "N/A"}x</div>
                <div className="text-xs text-gray-500 mt-1">Leverage</div>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-sm text-gray-600 mb-1">Analytics Score</div>
                <div className="text-xl font-semibold text-gray-900">{analyticsScore}</div>
                <div className="text-xs text-gray-500 mt-1">Out of 100</div>
              </div>
            </div>

            {/* Analyst Recommendations */}
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                  <Target className="size-5 text-indigo-600" />
                  Analyst Recommendations
                </h3>
                <div className="text-right">
                  <div className="text-sm text-gray-600">Average Rating</div>
                  <div className="text-lg font-semibold text-gray-900 flex items-center gap-1">
                    {indianApiData?.stockDetailsReusableData?.averageRating || "N/A"}
                    {indianApiData?.stockDetailsReusableData?.averageRating && indianApiData.stockDetailsReusableData.averageRating > 3 ? <TrendingUp className="size-4 text-green-500" /> : <TrendingDown className="size-4 text-red-500" />}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Pie Chart for Recommendations */}
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={indianApiData?.analystView?.filter(item => item.ratingName !== "Total").map((item, idx) => ({
                          name: item.ratingName,
                          value: Number(item.numberOfAnalystsLatest),
                          fill: ['#10B981', '#22C55E', '#6B7280', '#F97316', '#EF4444'][idx % 5]
                        })) || []}
                        cx="50%"
                        cy="50%"
                        innerRadius={40}
                        outerRadius={80}
                        paddingAngle={5}
                        dataKey="value"
                      >
                        {indianApiData?.analystView?.filter(item => item.ratingName !== "Total").map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={['#10B981', '#22C55E', '#6B7280', '#F97316', '#EF4444'][index % 5]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(value) => [value, 'Analysts']} />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </div>

                {/* Recommendation Cards */}
                <div className="space-y-3">
                  {indianApiData?.analystView?.filter(item => item.ratingName !== "Total").map((item, idx) => {
                    const total = Number(indianApiData.recosBar?.noOfRecommendations) || 1;
                    const percentage = (Number(item.numberOfAnalystsLatest) / total) * 100;
                    const colorMap = {
                      "Strong Buy": "bg-green-100 text-green-800 border-green-200",
                      "Buy": "bg-green-50 text-green-700 border-green-200",
                      "Hold": "bg-gray-100 text-gray-800 border-gray-200",
                      "Sell": "bg-red-50 text-red-700 border-red-200",
                      "Strong Sell": "bg-red-100 text-red-800 border-red-200"
                    };
                    return (
                      <div key={idx} className={`border rounded-lg p-3 flex items-center justify-between hover:shadow-md transition-shadow cursor-pointer ${colorMap[item.ratingName as keyof typeof colorMap] || 'bg-gray-50 text-gray-700 border-gray-200'}`}>
                        <div>
                          <div className="text-sm font-medium">{item.ratingName}</div>
                          <div className="text-xs opacity-75">{percentage.toFixed(1)}% of analysts</div>
                        </div>
                        <div className="text-right">
                          <div className="text-lg font-bold">{item.numberOfAnalystsLatest}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Consensus Rating */}
              <div className="border-t border-gray-200 pt-4 mt-6">
                <div className="flex items-center justify-between mb-4">
                  <span className="text-sm font-medium text-gray-700">Consensus Rating</span>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-900">{indianApiData?.recosBar?.meanValue?.toFixed(2) || "N/A"}</span>
                    {indianApiData?.recosBar?.meanValue && indianApiData.recosBar.meanValue < 3 ? <TrendingDown className="size-4 text-red-500" /> : <TrendingUp className="size-4 text-green-500" />}
                  </div>
                </div>
                <div className="flex items-center justify-center mb-2">
                  <div className="relative size-20">
                    <RadialBarChart width={80} height={80} cx="50%" cy="50%" innerRadius="60%" outerRadius="90%" barSize={10} data={[{ name: 'Rating', value: ((indianApiData?.recosBar?.meanValue || 3) / 5) * 100, fill: indianApiData?.recosBar?.meanValue && indianApiData.recosBar.meanValue < 3 ? '#EF4444' : '#10B981' }]}>
                      <RadialBar dataKey="value" cornerRadius={10} />
                    </RadialBarChart>
                    <div className="absolute inset-0 flex items-center justify-center text-sm font-semibold text-gray-900">{indianApiData?.recosBar?.meanValue?.toFixed(1) || "N/A"}</div>
                  </div>
                </div>
                <div className="flex justify-between text-xs text-gray-500">
                  <span>Sell (5)</span>
                  <span>Hold (3)</span>
                  <span>Buy (1)</span>
                </div>
              </div>
            </div>

            {/* Risk Assessment */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-sm text-gray-600 mb-1">Volatility (Std Dev)</div>
                <div className="text-xl font-semibold text-gray-900 mb-2">{indianApiData?.riskMeter?.stdDev?.toFixed(2) || "N/A"}%</div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className="bg-red-500 h-2 rounded-full"
                    style={{ width: `${Math.min(100, Math.max(0, (Number(indianApiData?.riskMeter?.stdDev) || 0) * 10))}%` }}
                  />
                </div>
                <div className="text-xs text-gray-500 mt-1">Higher = more volatile</div>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-sm text-gray-600 mb-1">Risk Category</div>
                <div className="text-xl font-semibold text-gray-900 mb-2">{indianApiData?.riskMeter?.categoryName || "N/A"}</div>
                <div className="text-xs text-gray-500 mt-1">Based on market analysis</div>
              </div>
            </div>

            {/* Peer Comparison */}
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-6">Peer Comparison</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm text-gray-600">Avg P/E Ratio</span>
                    <span className="text-sm font-semibold text-gray-900">{peerStats.avgPE}</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-blue-500 h-2 rounded-full"
                      style={{ width: `${Math.min(100, Math.max(0, (Number(peerStats.avgPE) || 0) * 2))}%` }}
                    />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm text-gray-600">Avg P/B Ratio</span>
                    <span className="text-sm font-semibold text-gray-900">{peerStats.avgPB}</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-green-500 h-2 rounded-full"
                      style={{ width: `${Math.min(100, Math.max(0, (Number(peerStats.avgPB) || 0) * 10))}%` }}
                    />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm text-gray-600">Avg Change %</span>
                    <span className={`text-sm font-semibold ${Number(peerStats.avgChange) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {peerStats.avgChange}%
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${Number(peerStats.avgChange) >= 0 ? 'bg-green-500' : 'bg-red-500'}`}
                      style={{ width: `${Math.min(100, Math.max(0, 50 + (Number(peerStats.avgChange) || 0) * 2))}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>



            {/* Additional Metrics */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer group">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-sm text-gray-600">Total Analysts</div>
                  <Users className="size-4 text-indigo-500" />
                </div>
                <div className="flex items-center gap-3">
                  <div className="relative size-12">
                    <RadialBarChart width={48} height={48} cx="50%" cy="50%" innerRadius="60%" outerRadius="90%" barSize={8} data={[{ name: 'Analysts', value: Math.min(100, (indianApiData?.recosBar?.noOfRecommendations || 0) * 2), fill: '#4F46E5' }]}>
                      <RadialBar dataKey="value" cornerRadius={10} />
                    </RadialBarChart>
                    <div className="absolute inset-0 flex items-center justify-center text-xs font-semibold text-indigo-600">{indianApiData?.recosBar?.noOfRecommendations || 0}</div>
                  </div>
                  <div>
                    <div className="text-xl font-semibold text-gray-900">{indianApiData?.recosBar?.noOfRecommendations || 0}</div>
                    <div className="text-xs text-gray-500">Coverage</div>
                  </div>
                </div>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer group">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-sm text-gray-600">Sector P/E</div>
                  {parseFloat(indianApiData?.stockDetailsReusableData?.sectorPriceToEarningsValueRatio || "0") < 20 ? <TrendingDown className="size-4 text-green-500" /> : <TrendingUp className="size-4 text-red-500" />}
                </div>
                <div className="text-xl font-semibold text-gray-900">{indianApiData?.stockDetailsReusableData?.sectorPriceToEarningsValueRatio || "N/A"}</div>
                <div className="text-xs text-gray-500 mt-1">Industry average</div>
                <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
                  <div
                    className="bg-blue-500 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(100, Math.max(0, (Number(indianApiData?.stockDetailsReusableData?.sectorPriceToEarningsValueRatio) || 0) * 2))}%` }}
                  />
                </div>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer group">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-sm text-gray-600">Mutual Fund Holding</div>
                  {parseFloat(indianApiData?.stockDetailsReusableData?.mutualFundShareHolding?.percentage || "0") > 5 ? <TrendingUp className="size-4 text-green-500" /> : <TrendingDown className="size-4 text-red-500" />}
                </div>
                <div className="text-xl font-semibold text-gray-900">{indianApiData?.stockDetailsReusableData?.mutualFundShareHolding?.percentage || "N/A"}%</div>
                <div className="text-xs text-gray-500 mt-1">Institutional ownership</div>
                <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
                  <div
                    className="bg-green-500 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(100, Math.max(0, (Number(indianApiData?.stockDetailsReusableData?.mutualFundShareHolding?.percentage) || 0) * 2))}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "News" && (
          <div className="space-y-4">
            {newsData.map((news, index) => (
              <div key={index} className="bg-white rounded-xl border border-gray-100 p-6 hover:shadow-lg transition-all duration-300 cursor-pointer group">
                <div className="flex items-start justify-between mb-3">
                  <h4 className="text-lg font-semibold text-gray-900 flex-1 mr-4 group-hover:text-indigo-600 transition-colors">{news.headline}</h4>
                  <div className="flex items-center gap-2 text-sm text-gray-500">
                    <Calendar className="size-4" />
                    {news.date}
                  </div>
                </div>
                <p className="text-gray-600 mb-4 leading-relaxed">{news.summary}</p>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="text-sm text-gray-500">
                      {news.timeToRead} min read
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="text-xs text-gray-400">Read Progress</div>
                      <div className="w-20 bg-gray-200 rounded-full h-1.5">
                        <div
                          className="bg-indigo-500 h-1.5 rounded-full transition-all duration-500 group-hover:bg-indigo-600"
                          style={{ width: `${Math.min(100, (news.timeToRead / 10) * 100)}%` }}
                        ></div>
                      </div>
                    </div>
                  </div>
                  <Button variant="outline" size="sm" className="hover:bg-indigo-50 hover:border-indigo-300 transition-colors" asChild>
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