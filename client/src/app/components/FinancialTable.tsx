import { getCompanyById } from "../data/companies";
import { Card } from "./ui/card";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface FinancialTableProps {
  companyId: string;
  years?: number;
}

function TrendCell({ current, previous, value, format = "number" }: {
  current: number;
  previous?: number;
  value: string;
  format?: "number" | "percent";
}) {
  if (!previous) return <td className="px-4 py-3 text-right text-sm font-medium text-gray-900">{value}</td>;

  const diff = ((current - previous) / Math.abs(previous)) * 100;
  const isUp = diff > 0;
  const isFlat = Math.abs(diff) < 0.5;

  return (
    <td className="px-4 py-3 text-right">
      <div className="flex items-center justify-end gap-1.5">
        <span className="text-sm font-medium text-gray-900">{value}</span>
        {!isFlat && (
          <span className={`flex items-center gap-0.5 text-xs ${isUp ? "text-emerald-500" : "text-red-500"}`}>
            {isUp ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
          </span>
        )}
        {isFlat && <Minus className="size-3 text-gray-300" />}
      </div>
    </td>
  );
}

const rows: { key: keyof any; label: string; format: (v: number) => string; higherBetter: boolean }[] = [
  { key: "sales", label: "Revenue (₹Cr)", format: (v) => (v / 10).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ","), higherBetter: true },
  { key: "ebitda", label: "EBITDA (₹Cr)", format: (v) => (v / 10).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ","), higherBetter: true },
  { key: "opm", label: "OPM (%)", format: (v) => `${v}%`, higherBetter: true },
  { key: "pat", label: "PAT (₹Cr)", format: (v) => (v / 10).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ","), higherBetter: true },
  { key: "eps", label: "EPS (₹)", format: (v) => `₹${v.toFixed(1)}`, higherBetter: true },
  { key: "roce", label: "ROCE (%)", format: (v) => `${v}%`, higherBetter: true },
  { key: "de", label: "D/E Ratio", format: (v) => `${v}x`, higherBetter: false },
  { key: "cfo", label: "CFO (₹Cr)", format: (v) => (v / 10).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ","), higherBetter: true },
];

export function FinancialTable({ companyId, years = 5 }: FinancialTableProps) {
  const company = getCompanyById(companyId);
  if (!company) return null;

  const financials = company.financials.slice(0, years);

  return (
    <Card className="bg-white border border-gray-100 shadow-sm rounded-2xl overflow-hidden max-w-full">
      <div className="px-5 py-4 border-b border-gray-50">
        <h4 className="font-semibold text-gray-900 text-sm">{company.name}</h4>
        <p className="text-xs text-gray-400 mt-0.5">Historical Financial Summary</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50/80 border-b border-gray-100">
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide w-36">
                Metric
              </th>
              {financials.map((f) => (
                <th key={f.year} className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  FY{f.year}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {rows.map((row, rowIdx) => {
              const isHighlighted = row.key === "roce" || row.key === "opm";
              return (
                <tr key={rowIdx} className={`hover:bg-gray-50/50 transition-colors ${isHighlighted ? "bg-indigo-50/20" : ""}`}>
                  <td className="px-4 py-3 text-sm font-medium text-gray-700 whitespace-nowrap">
                    {row.label}
                  </td>
                  {financials.map((f, idx) => {
                    const prev = financials[idx + 1];
                    const rawVal = f[row.key as keyof typeof f] as number;
                    const prevVal = prev ? (prev[row.key as keyof typeof prev] as number) : undefined;
                    return (
                      <TrendCell
                        key={f.year}
                        current={rawVal}
                        previous={prevVal}
                        value={row.format(rawVal)}
                      />
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
