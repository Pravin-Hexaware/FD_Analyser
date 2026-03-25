import { getCompanyById } from "../data/companies";
import { Card } from "./ui/card";
import { Building2, TrendingUp, DollarSign, Activity, ArrowRight, BarChart3 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "./ui/button";

interface CompanyInfoCardProps {
  companyId: string;
}

const sectorColors: Record<string, { bg: string; text: string; border: string }> = {
  "Energy": { bg: "bg-orange-50", text: "text-orange-600", border: "border-orange-200" },
  "Technology": { bg: "bg-blue-50", text: "text-blue-600", border: "border-blue-200" },
  "Consumer Goods": { bg: "bg-green-50", text: "text-green-600", border: "border-green-200" },
  "Financial Services": { bg: "bg-purple-50", text: "text-purple-600", border: "border-purple-200" },
};

export function CompanyInfoCard({ companyId }: CompanyInfoCardProps) {
  const navigate = useNavigate();
  const company = getCompanyById(companyId);
  if (!company) return null;

  const latest = company.financials[0];
  const prev = company.financials[1];
  const salesGrowth = (((latest.sales - prev.sales) / prev.sales) * 100).toFixed(1);
  const sectorStyle = sectorColors[company.sector] || { bg: "bg-gray-50", text: "text-gray-600", border: "border-gray-200" };

  return (
    <Card className="bg-white border border-gray-100 shadow-sm overflow-hidden rounded-2xl max-w-sm">
      {/* Header */}
      <div className="px-5 pt-5 pb-4 border-b border-gray-50">
        <div className="flex items-start justify-between mb-2">
          <div>
            <h3 className="font-semibold text-gray-900">{company.name}</h3>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs font-medium text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
                {company.symbol}
              </span>
              <span className="text-xs text-gray-400">BSE {company.bseCode}</span>
            </div>
          </div>
          <div className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border ${sectorStyle.bg} ${sectorStyle.text} ${sectorStyle.border}`}>
            <Building2 className="size-3" />
            {company.sector}
          </div>
        </div>
        <div className="text-xs text-gray-500">{company.industry}</div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-0 divide-x divide-y divide-gray-50">
        {[
          { label: `Sales FY${latest.year}`, value: `₹${(latest.sales / 1000).toFixed(0)}B`, icon: DollarSign, sub: `+${salesGrowth}% YoY`, subColor: "text-emerald-500" },
          { label: "EBITDA Margin", value: `${latest.opm}%`, icon: Activity, sub: "Operating Profit", subColor: "text-gray-400" },
          { label: "ROCE", value: `${latest.roce}%`, icon: TrendingUp, sub: "Return on Capital", subColor: "text-gray-400" },
          { label: "D/E Ratio", value: `${latest.de}x`, icon: BarChart3, sub: latest.de < 1 ? "Conservative" : "Leveraged", subColor: latest.de < 1 ? "text-emerald-500" : "text-amber-500" },
        ].map((kpi, idx) => (
          <div key={idx} className="flex items-center gap-2.5 px-4 py-3">
            <div className="size-7 rounded-lg bg-indigo-50 flex items-center justify-center flex-shrink-0">
              <kpi.icon className="size-3.5 text-indigo-600" />
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-0.5">{kpi.label}</div>
              <div className="font-semibold text-gray-900 text-sm">{kpi.value}</div>
              <div className={`text-xs ${kpi.subColor}`}>{kpi.sub}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="px-5 py-3.5 flex gap-2 bg-gray-50/50">
        <Button
          size="sm"
          variant="outline"
          onClick={() => navigate(`/company/${companyId}`)}
          className="flex-1 text-xs"
        >
          Full Profile
        </Button>
        <Button
          size="sm"
          onClick={() => navigate("/compare")}
          className="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white text-xs"
        >
          Compare
          <ArrowRight className="size-3 ml-1" />
        </Button>
      </div>
    </Card>
  );
}
