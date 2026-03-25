// Mock chatbot responses and AI report generation
import type { CompanyData } from "./companies";
import { companies } from "./companies";
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  widget?: ChatWidget;
}

export type ChatWidget = 
  | { type: "company-card"; companyId: string }
  | { type: "financial-table"; companyId: string; years?: number }
  | { type: "comparison-table"; companyIds: string[] }
  | { type: "chart"; companyIds: string[]; metric: string };

export interface AIReport {
  id: string;
  title: string;
  generatedAt: Date;
  companyIds: string[];
  summary: string;
  sections: ReportSection[];
  shareLink: string;
}

export interface ReportSection {
  title: string;
  content: string;
  metrics?: { label: string; value: string }[];
}

export function generateAIReport(companyIds: string[], companies: CompanyData[]): AIReport {
  const selectedCompanies = companies.filter(c => companyIds.includes(c.id));
  const reportId = `report-${Date.now()}`;
  
  if (selectedCompanies.length === 1) {
    const company = selectedCompanies[0];
    const latest = company.financials[0];
    const oldest = company.financials[company.financials.length - 1];
    
    const salesGrowth = (((latest.sales - oldest.sales) / oldest.sales) * 100).toFixed(1);
    const patGrowth = (((latest.pat - oldest.pat) / oldest.pat) * 100).toFixed(1);
    
    return {
      id: reportId,
      title: `${company.name} - Financial Analysis Report`,
      generatedAt: new Date(),
      companyIds,
      summary: `${company.name} operates in the ${company.sector} sector, specifically in ${company.industry}. Over the past 5 years, the company has demonstrated ${Number(salesGrowth) > 0 ? 'strong' : 'moderate'} growth with sales increasing by ${salesGrowth}% and profitability growing by ${patGrowth}%.`,
      sections: [
        {
          title: "Executive Summary",
          content: `${company.name} (${company.symbol}) is a leading player in the ${company.industry} industry. The company has shown consistent performance with an operating profit margin of ${latest.opm}% and a ROCE of ${latest.roce}%, indicating efficient capital utilization.`
        },
        {
          title: "Revenue & Profitability Trends",
          content: `Sales have grown from ₹${(oldest.sales / 1000).toFixed(0)}B in ${oldest.year} to ₹${(latest.sales / 1000).toFixed(0)}B in ${latest.year}, representing a ${salesGrowth}% increase. Profit after tax has similarly grown from ₹${(oldest.pat / 1000).toFixed(0)}B to ₹${(latest.pat / 1000).toFixed(0)}B. The company maintains a healthy operating margin of around ${latest.opm}%.`,
          metrics: [
            { label: "5Y Sales CAGR", value: `${((Math.pow(latest.sales / oldest.sales, 1/5) - 1) * 100).toFixed(1)}%` },
            { label: "5Y PAT CAGR", value: `${((Math.pow(latest.pat / oldest.pat, 1/5) - 1) * 100).toFixed(1)}%` },
            { label: "Latest OPM", value: `${latest.opm}%` },
          ]
        },
        {
          title: "Cash Flow Quality",
          content: `The company generates strong operating cash flows of ₹${(latest.cfo / 1000).toFixed(0)}B in ${latest.year}, which is ${((latest.cfo / latest.pat) * 100).toFixed(0)}% of its profit after tax. This indicates high quality earnings backed by actual cash generation.`,
          metrics: [
            { label: "CFO", value: `₹${(latest.cfo / 1000).toFixed(0)}B` },
            { label: "CFO/PAT Ratio", value: `${((latest.cfo / latest.pat) * 100).toFixed(0)}%` },
          ]
        },
        {
          title: "Leverage & Return Metrics",
          content: `With a debt-to-equity ratio of ${latest.de}, the company maintains ${latest.de < 0.5 ? 'a conservative' : 'a moderate'} leverage profile. The return on capital employed (ROCE) of ${latest.roce}% ${latest.roce > 20 ? 'significantly exceeds' : 'is competitive with'} the cost of capital, creating value for shareholders.`,
          metrics: [
            { label: "D/E Ratio", value: `${latest.de}` },
            { label: "ROCE", value: `${latest.roce}%` },
            { label: "EPS", value: `₹${latest.eps}` },
          ]
        },
        {
          title: "Risk Observations",
          content: `Key risks include ${company.sector === 'Technology' ? 'competition from global players, talent retention, and currency fluctuations' : company.sector === 'Energy' ? 'commodity price volatility, regulatory changes, and environmental concerns' : company.sector === 'Financial Services' ? 'credit risk, interest rate changes, and regulatory compliance' : 'market competition and demand fluctuations'}. The company's ${latest.de < 0.5 ? 'low leverage' : 'moderate leverage'} provides flexibility to navigate challenges.`
        }
      ],
      shareLink: `https://finbot.app/reports/${reportId}`
    };
  } else {
    // Comparison report
    const title = selectedCompanies.map(c => c.symbol).join(" vs ");
    
    return {
      id: reportId,
      title: `Comparative Analysis: ${title}`,
      generatedAt: new Date(),
      companyIds,
      summary: `This comparative analysis examines ${selectedCompanies.length} companies across key financial metrics to identify relative strengths and investment opportunities.`,
      sections: [
        {
          title: "Executive Summary",
          content: `This report compares ${selectedCompanies.map(c => c.name).join(", ")}. The analysis covers revenue growth, profitability margins, return ratios, and financial leverage to provide a comprehensive view of relative performance.`
        },
        {
          title: "Revenue & Growth Comparison",
          content: `Among the companies analyzed, ${selectedCompanies.reduce((max, c) => c.financials[0].sales > max.financials[0].sales ? c : max).name} leads in absolute revenue size with ₹${(selectedCompanies.reduce((max, c) => c.financials[0].sales > max.financials[0].sales ? c : max).financials[0].sales / 1000).toFixed(0)}B in sales.`,
          metrics: selectedCompanies.map(c => ({
            label: c.symbol,
            value: `₹${(c.financials[0].sales / 1000).toFixed(0)}B`
          }))
        },
        {
          title: "Profitability Comparison",
          content: `Operating profit margins vary significantly across the companies. ${selectedCompanies.reduce((max, c) => c.financials[0].opm > max.financials[0].opm ? c : max).name} demonstrates the highest OPM at ${selectedCompanies.reduce((max, c) => c.financials[0].opm > max.financials[0].opm ? c : max).financials[0].opm}%, indicating superior operational efficiency.`,
          metrics: selectedCompanies.map(c => ({
            label: c.symbol,
            value: `${c.financials[0].opm}%`
          }))
        },
        {
          title: "Return on Capital",
          content: `${selectedCompanies.reduce((max, c) => c.financials[0].roce > max.financials[0].roce ? c : max).name} achieves the highest ROCE at ${selectedCompanies.reduce((max, c) => c.financials[0].roce > max.financials[0].roce ? c : max).financials[0].roce}%, demonstrating excellent capital efficiency. This suggests the company generates superior returns on invested capital compared to peers.`,
          metrics: selectedCompanies.map(c => ({
            label: c.symbol,
            value: `${c.financials[0].roce}%`
          }))
        },
        {
          title: "Financial Leverage",
          content: `Debt levels vary across the portfolio. ${selectedCompanies.reduce((min, c) => c.financials[0].de < min.financials[0].de ? c : min).name} maintains the lowest leverage with a D/E ratio of ${selectedCompanies.reduce((min, c) => c.financials[0].de < min.financials[0].de ? c : min).financials[0].de}, providing greater financial flexibility.`,
          metrics: selectedCompanies.map(c => ({
            label: c.symbol,
            value: `${c.financials[0].de}`
          }))
        },
        {
          title: "Investment Perspective",
          content: `Based on the analysis, investors should consider their investment objectives: growth investors may favor companies with strong revenue momentum, while value investors might prefer those with higher ROCE and lower leverage. Diversification across these companies could provide balanced exposure to the ${[...new Set(selectedCompanies.map(c => c.sector))].join(" and ")} sector${selectedCompanies.map(c => c.sector).filter((v, i, a) => a.indexOf(v) === i).length > 1 ? 's' : ''}.`
        }
      ],
      shareLink: `https://finbot.app/reports/${reportId}`
    };
  }
}

export function processChatQuery(query: string, companies: CompanyData[]): ChatMessage {
  const messageId = `msg-${Date.now()}`;
  const q = query.toLowerCase();
  
  // Check for comparison queries
  if (q.includes("compare") || q.includes("vs")) {
    const matchedCompanies = companies.filter(c => 
      q.includes(c.name.toLowerCase()) || q.includes(c.symbol.toLowerCase())
    );
    
    if (matchedCompanies.length >= 2) {
      return {
        id: messageId,
        role: "assistant",
        content: `Here's a comparison of ${matchedCompanies.map(c => c.name).join(" and ")}:`,
        timestamp: new Date(),
        widget: {
          type: "comparison-table",
          companyIds: matchedCompanies.map(c => c.id)
        }
      };
    }
  }
  
  // Check for financials query
  if (q.includes("financial") || q.includes("show") || q.includes("data")) {
    const matchedCompany = companies.find(c => 
      q.includes(c.name.toLowerCase()) || q.includes(c.symbol.toLowerCase())
    );
    
    if (matchedCompany) {
      return {
        id: messageId,
        role: "assistant",
        content: `Here are the financial details for ${matchedCompany.name}:`,
        timestamp: new Date(),
        widget: {
          type: "financial-table",
          companyId: matchedCompany.id,
          years: 5
        }
      };
    }
  }
  
  // Check for company info query
  const matchedCompany = companies.find(c => 
    q.includes(c.name.toLowerCase()) || q.includes(c.symbol.toLowerCase())
  );
  
  if (matchedCompany) {
    return {
      id: messageId,
      role: "assistant",
      content: `Here's information about ${matchedCompany.name}:`,
      timestamp: new Date(),
      widget: {
        type: "company-card",
        companyId: matchedCompany.id
      }
    };
  }
  
  // Default response
  return {
    id: messageId,
    role: "assistant",
    content: "I can help you with financial data, company comparisons, and analysis. Try asking:\n• \"Show financials for Reliance\"\n• \"Compare TCS and Infosys\"\n• \"Generate report for Asian Paints\"",
    timestamp: new Date()
  };
}
