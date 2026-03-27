import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getCompanyById } from "../data/companies";
import { Card } from "./ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import { Button } from "./ui/button";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis
} from "recharts";
import { Sparkles } from "lucide-react";

interface ComparisonTableProps {
  companyIds: string[];
}

const COLORS = ["#4f46e5", "#0d9488", "#7c3aed", "#dc2626", "#ea580c"];

const metrics = [
  { key: "sales", label: "Revenue (₹Cr)", fmt: (v: number) => (v / 10).toLocaleString("en-IN", { maximumFractionDigits: 0 }), higherBetter: true },
  { key: "ebitda", label: "EBITDA (₹Cr)", fmt: (v: number) => (v / 10).toLocaleString("en-IN", { maximumFractionDigits: 0 }), higherBetter: true },
  { key: "opm", label: "OPM (%)", fmt: (v: number) => `${v}%`, higherBetter: true },
  { key: "pat", label: "PAT (₹Cr)", fmt: (v: number) => (v / 10).toLocaleString("en-IN", { maximumFractionDigits: 0 }), higherBetter: true },
  { key: "eps", label: "EPS (₹)", fmt: (v: number) => `₹${v.toFixed(1)}`, higherBetter: true },
  { key: "roce", label: "ROCE (%)", fmt: (v: number) => `${v}%`, higherBetter: true },
  { key: "de", label: "D/E Ratio", fmt: (v: number) => `${v}x`, higherBetter: false },
  { key: "cfo", label: "CFO (₹Cr)", fmt: (v: number) => (v / 10).toLocaleString("en-IN", { maximumFractionDigits: 0 }), higherBetter: true },
];

export function ComparisonTable({ companyIds }: ComparisonTableProps) {
  const [activeTab, setActiveTab] = useState("table");
  const navigate = useNavigate();
  const companies = companyIds.map((id) => getCompanyById(id)).filter(Boolean) as NonNullable<ReturnType<typeof getCompanyById>>[];

  if (companies.length === 0) return null;

  // Chart data for revenue trend
  const chartData = [...companies[0].financials].reverse().map((_, idx) => {
    const point: Record<string, any> = {
      year: companies[0].financials[companies[0].financials.length - 1 - idx].year
    };
    companies.forEach((c) => {
      point[c.symbol] = c.financials[c.financials.length - 1 - idx].sales / 1000;
    });
    return point;
  });

  // Radar data
  const radarData = [
    { subject: "OPM", fullMark: 50 },
    { subject: "ROCE", fullMark: 60 },
    { subject: "EPS Score", fullMark: 100 },
    { subject: "CFO/PAT", fullMark: 130 },
    { subject: "Growth", fullMark: 30 },
  ].map((item) => {
    const point: Record<string, any> = { subject: item.subject, fullMark: item.fullMark };
    companies.forEach((c) => {
      const l = c.financials[0];
      const o = c.financials[c.financials.length - 1];
      if (item.subject === "OPM") point[c.symbol] = l.opm;
      else if (item.subject === "ROCE") point[c.symbol] = l.roce;
      else if (item.subject === "EPS Score") point[c.symbol] = Math.min(l.eps / 2, 100);
      else if (item.subject === "CFO/PAT") point[c.symbol] = (l.cfo / l.pat) * 100;
      else if (item.subject === "Growth") point[c.symbol] = ((l.sales - o.sales) / o.sales) * 100;
    });
    return point;
  });

  const getBestIdx = (key: string, higherBetter: boolean) => {
    const vals = companies.map((c) => c.financials[0][key as keyof typeof c.financials[0]] as number);
    if (higherBetter) return vals.indexOf(Math.max(...vals));
    return vals.indexOf(Math.min(...vals));
  };

  return (
    <Card className="bg-white border border-gray-100 shadow-sm rounded-2xl overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
        <div>
          <h4 className="font-semibold text-gray-900 text-sm">Company Comparison</h4>
          <p className="text-xs text-gray-400 mt-0.5">FY2025 latest data · {companies.length} companies</p>
        </div>
        <Button
          size="sm"
          onClick={() => navigate("/compare", { state: { companyIds } })}
          className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs"
        >
          <Sparkles className="size-3.5 mr-1.5" />
          AI Report
        </Button>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="px-5 pt-4">
        <TabsList className="bg-gray-100 p-1 rounded-lg mb-4">
          <TabsTrigger value="table" className="text-xs rounded-md">Table</TabsTrigger>
          <TabsTrigger value="chart" className="text-xs rounded-md">Revenue Trend</TabsTrigger>
          <TabsTrigger value="radar" className="text-xs rounded-md">Spider Chart</TabsTrigger>
        </TabsList>

        <TabsContent value="table" className="pb-5">
          <div className="overflow-x-auto rounded-xl border border-gray-100">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Metric
                  </th>
                  {companies.map((c, idx) => (
                    <th key={c.id} className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide" style={{ color: COLORS[idx] }}>
                      {c.symbol}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {metrics.map((m, mIdx) => {
                  const bestIdx = getBestIdx(m.key, m.higherBetter);
                  return (
                    <tr key={mIdx} className="hover:bg-gray-50/50 transition-colors">
                      <td className="px-4 py-3 font-medium text-gray-700">{m.label}</td>
                      {companies.map((c, cIdx) => {
                        const val = c.financials[0][m.key as keyof typeof c.financials[0]] as number;
                        const isBest = cIdx === bestIdx;
                        return (
                          <td key={c.id} className={`px-4 py-3 text-right ${isBest ? "font-semibold" : "text-gray-700"}`}>
                            <span style={{ color: isBest ? COLORS[cIdx] : undefined }}>
                              {m.fmt(val)}
                            </span>
                            {isBest && (
                              <span className="text-xs ml-1 text-amber-400">★</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </TabsContent>

        <TabsContent value="chart" className="pb-5">
          <div className="h-72 rounded-xl border border-gray-100 bg-gray-50/50 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="year" tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#fff", border: "1px solid #e2e8f0", borderRadius: "12px", fontSize: 12 }}
                  formatter={(val: any) => [`₹${val}B`, ""]}
                />
                <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
                {companies.map((c, idx) => (
                  <Line
                    key={c.id}
                    type="monotone"
                    dataKey={c.symbol}
                    stroke={COLORS[idx]}
                    strokeWidth={2.5}
                    dot={{ r: 4, fill: COLORS[idx] }}
                    activeDot={{ r: 6 }}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </TabsContent>

        <TabsContent value="radar" className="pb-5">
          <div className="h-72 rounded-xl border border-gray-100 bg-gray-50/50 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData}>
                <PolarGrid stroke="#e2e8f0" />
                <PolarAngleAxis dataKey="subject" tick={{ fill: "#64748b", fontSize: 11 }} />
                <PolarRadiusAxis tick={false} axisLine={false} />
                {companies.map((c, idx) => (
                  <Radar
                    key={c.id}
                    name={c.symbol}
                    dataKey={c.symbol}
                    stroke={COLORS[idx]}
                    fill={COLORS[idx]}
                    fillOpacity={0.15}
                    strokeWidth={2}
                  />
                ))}
                <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#fff", border: "1px solid #e2e8f0", borderRadius: "12px", fontSize: 12 }}
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </TabsContent>
      </Tabs>
    </Card>
  );
}
