import { useState, useEffect } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { Download, Share2, RefreshCw, FileText, CheckCircle, TrendingUp, Shield, BarChart3, AlertTriangle, Lightbulb } from "lucide-react";
import { Button } from "../components/ui/button";
import type{ AIReport, generateAIReport } from "../data/chatbot";
import { getCompanyById } from "../data/companies";
import { toast } from "sonner";
import { AppShell } from "../components/AppShell";

const SECTION_ICONS: Record<string, any> = {
  "Executive Summary": CheckCircle,
  "Revenue & Profitability Trends": TrendingUp,
  "Cash Flow Quality": BarChart3,
  "Leverage & Return Metrics": Shield,
  "Risk Observations": AlertTriangle,
  "Revenue & Growth Comparison": TrendingUp,
  "Profitability Comparison": BarChart3,
  "Return on Capital": Shield,
  "Financial Leverage": Shield,
  "Investment Perspective": Lightbulb,
};

const SECTION_COLORS: Record<string, string> = {
  "Executive Summary": "indigo",
  "Revenue & Profitability Trends": "teal",
  "Cash Flow Quality": "blue",
  "Leverage & Return Metrics": "purple",
  "Risk Observations": "amber",
  "Revenue & Growth Comparison": "teal",
  "Profitability Comparison": "indigo",
  "Return on Capital": "purple",
  "Financial Leverage": "orange",
  "Investment Perspective": "green",
};

const COLOR_CLASSES: Record<string, { bg: string; icon: string; border: string }> = {
  indigo: { bg: "bg-indigo-50", icon: "text-indigo-600", border: "border-indigo-100" },
  teal: { bg: "bg-teal-50", icon: "text-teal-600", border: "border-teal-100" },
  blue: { bg: "bg-blue-50", icon: "text-blue-600", border: "border-blue-100" },
  purple: { bg: "bg-purple-50", icon: "text-purple-600", border: "border-purple-100" },
  amber: { bg: "bg-amber-50", icon: "text-amber-600", border: "border-amber-100" },
  orange: { bg: "bg-orange-50", icon: "text-orange-600", border: "border-orange-100" },
  green: { bg: "bg-green-50", icon: "text-green-600", border: "border-green-100" },
};

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [report, setReport] = useState<AIReport | null>(null);
  const [activeSection, setActiveSection] = useState(0);
  const [isGenerating, setIsGenerating] = useState(false);

  useEffect(() => {
    if ((location.state as any)?.report) {
      setReport((location.state as any).report);
    } else {
      const sampleReport = generateAIReport(
        ["reliance"],
        [getCompanyById("reliance")].filter(Boolean) as any
      );
      setReport(sampleReport);
    }
  }, [id, location.state]);

  const handleDownload = () => {
    toast.success("PDF downloaded!", { description: "Saved to your downloads folder." });
  };

  const handleShare = () => {
    if (report) {
      navigator.clipboard.writeText(report.shareLink);
      toast.success("Link copied!", { description: "Share this link to view the report." });
    }
  };

  const handleRegenerate = () => {
    if (!report) return;
    setIsGenerating(true);
    setTimeout(() => {
      const cos = report.companyIds.map((id) => getCompanyById(id)).filter(Boolean) as any;
      setReport(generateAIReport(report.companyIds, cos));
      setIsGenerating(false);
      toast.success("Report regenerated!");
    }, 1500);
  };

  if (!report) {
    return (
      <AppShell title="Loading Report...">
        <div className="flex items-center justify-center h-64">
          <div className="size-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      breadcrumb={[
        { label: "Dashboard", href: "/" },
        { label: "Reports", href: "/compare" },
        { label: report.title.length > 40 ? report.title.slice(0, 40) + "..." : report.title },
      ]}
      actions={
        <>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRegenerate}
            disabled={isGenerating}
            className="text-xs"
          >
            <RefreshCw className={`size-3.5 mr-1.5 ${isGenerating ? "animate-spin" : ""}`} />
            Regenerate
          </Button>
          <Button variant="outline" size="sm" onClick={handleShare} className="text-xs">
            <Share2 className="size-3.5 mr-1.5" />
            Share
          </Button>
          <Button
            size="sm"
            onClick={handleDownload}
            className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs"
          >
            <Download className="size-3.5 mr-1.5" />
            Download PDF
          </Button>
        </>
      }
    >
      <div className="flex h-full">
        {/* TOC Sidebar */}
        <div className="w-56 border-r border-gray-100 bg-white flex-shrink-0 p-4 overflow-y-auto">
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 px-2">
            Contents
          </div>
          {report.sections.map((section, idx) => {
            const Icon = SECTION_ICONS[section.title] || FileText;
            const color = SECTION_COLORS[section.title] || "indigo";
            const c = COLOR_CLASSES[color] || COLOR_CLASSES.indigo;
            return (
              <button
                key={idx}
                onClick={() => {
                  setActiveSection(idx);
                  document.getElementById(`section-${idx}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
                className={`w-full flex items-start gap-2.5 px-3 py-2.5 rounded-xl mb-1 text-left transition-all ${
                  activeSection === idx
                    ? `${c.bg} ${c.border} border`
                    : "hover:bg-gray-50"
                }`}
              >
                <Icon className={`size-3.5 mt-0.5 flex-shrink-0 ${activeSection === idx ? c.icon : "text-gray-400"}`} />
                <span className={`text-xs leading-tight ${activeSection === idx ? "font-medium text-gray-900" : "text-gray-500"}`}>
                  {section.title}
                </span>
              </button>
            );
          })}
        </div>

        {/* Report Content */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-8 py-6">
            {/* Report Header */}
            <div className="bg-gradient-to-br from-indigo-600 to-indigo-800 rounded-2xl p-6 mb-6 text-white relative overflow-hidden">
              <div
                className="absolute inset-0 opacity-10"
                style={{
                  backgroundImage: "radial-gradient(circle at 2px 2px, white 1px, transparent 0)",
                  backgroundSize: "24px 24px",
                }}
              />
              <div className="relative">
                <div className="flex items-start gap-4 mb-4">
                  <div className="size-12 rounded-xl bg-white/20 backdrop-blur flex items-center justify-center flex-shrink-0">
                    <FileText className="size-6 text-white" />
                  </div>
                  <div>
                    <h1 className="text-xl font-semibold mb-1">{report.title}</h1>
                    <p className="text-indigo-200 text-sm">
                      Generated {report.generatedAt.toLocaleDateString("en-US", {
                        year: "numeric",
                        month: "long",
                        day: "numeric",
                      })} · AI-powered analysis
                    </p>
                  </div>
                </div>

                {/* Company chips */}
                <div className="flex flex-wrap gap-2">
                  {report.companyIds.map((cid) => {
                    const co = getCompanyById(cid);
                    if (!co) return null;
                    return (
                      <span key={cid} className="px-3 py-1 bg-white/20 rounded-full text-sm font-medium">
                        {co.symbol}
                      </span>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Executive Summary */}
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 mb-5">
              <div className="flex items-center gap-3 mb-3">
                <div className="size-8 rounded-lg bg-indigo-50 flex items-center justify-center">
                  <CheckCircle className="size-4 text-indigo-600" />
                </div>
                <h2 className="font-semibold text-gray-900">Executive Summary</h2>
              </div>
              <p className="text-gray-600 text-sm leading-relaxed">{report.summary}</p>
            </div>

            {/* Sections */}
            {report.sections.map((section, idx) => {
              const Icon = SECTION_ICONS[section.title] || FileText;
              const color = SECTION_COLORS[section.title] || "indigo";
              const c = COLOR_CLASSES[color] || COLOR_CLASSES.indigo;

              return (
                <div
                  key={idx}
                  id={`section-${idx}`}
                  className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 mb-5 scroll-mt-6"
                >
                  <div className="flex items-center gap-3 mb-4">
                    <div className={`size-9 rounded-xl ${c.bg} flex items-center justify-center`}>
                      <Icon className={`size-4.5 ${c.icon}`} />
                    </div>
                    <h2 className="font-semibold text-gray-900">{section.title}</h2>
                  </div>

                  <p className="text-gray-600 text-sm leading-relaxed mb-4">{section.content}</p>

                  {section.metrics && section.metrics.length > 0 && (
                    <div className={`grid grid-cols-${Math.min(section.metrics.length, 3)} gap-3 pt-4 border-t border-gray-50`}
                      style={{ gridTemplateColumns: `repeat(${Math.min(section.metrics.length, 3)}, 1fr)` }}
                    >
                      {section.metrics.map((metric, mIdx) => (
                        <div key={mIdx} className={`rounded-xl p-4 ${c.bg} ${c.border} border`}>
                          <div className="text-xs text-gray-500 mb-1">{metric.label}</div>
                          <div className={`text-xl font-semibold ${c.icon}`}>{metric.value}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Share Section */}
            <div className="bg-gradient-to-br from-indigo-50 to-blue-50 rounded-2xl border border-indigo-100 p-6 mb-6">
              <h3 className="font-semibold text-gray-900 mb-1">Share this Report</h3>
              <p className="text-sm text-gray-500 mb-4">Anyone with the link can view this analysis</p>
              <div className="flex gap-3">
                <div className="flex-1 bg-white rounded-xl border border-indigo-200 px-4 py-2.5 text-sm text-gray-500 truncate">
                  {report.shareLink}
                </div>
                <Button variant="outline" onClick={handleShare} className="border-indigo-200 text-indigo-600 hover:bg-indigo-50">
                  <Share2 className="size-4 mr-2" />
                  Copy
                </Button>
              </div>
            </div>

            {/* Footer Actions */}
            <div className="flex gap-3 pb-8">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => navigate("/compare")}
              >
                New Comparison
              </Button>
              <Button
                className="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white"
                onClick={() => navigate("/chat")}
              >
                Ask FinBot More
              </Button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
