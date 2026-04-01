import type { ReactNode } from "react";
import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  BarChart3, MessageSquare, Settings, Home,
  ChevronRight, BarChart2
  MessageSquare, Settings, Home,
  ChevronRight, HelpCircle, Bell, BarChart2
} from "lucide-react";
import { fetchCompanies, type CompanyInfo } from "../services/api";
import { Sidebar } from "../../components/Sidebar";

interface AppShellProps {
  children: ReactNode;
  title?: string;
  subtitle?: string;
  breadcrumb?: { label: string; href?: string }[];
  actions?: ReactNode;
  noPadding?: boolean;
}

const navItems = [
  { path: "/", icon: Home, label: "Dashboard" },
  { path: "/chat", icon: MessageSquare, label: "AI Chat" },
  { path: "/compare", icon: BarChart2, label: "Compare" },
  { path: "/admin", icon: Settings, label: "Admin" },
];

const sectorColors: Record<string, string> = {
  "Energy": "bg-orange-400",
  "Technology": "bg-blue-400",
  "Consumer Goods": "bg-green-400",
  "Financial Services": "bg-purple-400",
};

export function AppShell({ children, title, subtitle, breadcrumb, actions, noPadding }: AppShellProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [companiesList, setCompaniesList] = useState<CompanyInfo[]>([]);

  useEffect(() => {
    const loadCompanies = async () => {
      try {
        const data = await fetchCompanies();
        setCompaniesList(data);
      } catch (error) {
        console.error("Failed to load companies:", error);
        setCompaniesList([]);
      }
    };

    loadCompanies();
  }, []);

  const sidebarContent = (
    <div className="space-y-0.5">
      {companiesList.map((company, idx) => {
        const isActive = location.pathname === `/company/${company.scrip_code}`;
        return (
          <button
            key={`${company.scrip_code}-${idx}`}
            onClick={() => navigate(`/company/${company.scrip_code}`)}
            className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg transition-all text-sm ${
              isActive
                ? "bg-slate-700 text-white"
                : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
            }`}
          >
            <div
              className={`size-2 rounded-full flex-shrink-0 ${
                sectorColors[company.sector || ""] || "bg-slate-500"
              }`}
            />
            <span className="font-medium">{company.symbol}</span>
            <span className="text-xs text-slate-600 ml-auto truncate max-w-16">
              {company.sector ? company.sector.split(" ")[0] : "N/A"}
            </span>
          </button>
        );
      })}
    </div>
  );

  const footer = (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 cursor-pointer transition-colors">
      <div className="size-8 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center flex-shrink-0">
        <span className="text-white text-xs font-semibold">PR</span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-slate-300 text-sm truncate">Pravin Raj</div>
        <div className="text-xs text-slate-600 truncate">Analyst</div>
      </div>
    </div>
  );

  return (
    <div className="h-screen flex bg-slate-50 overflow-hidden">
      <Sidebar
        navItems={navItems}
        activePath={location.pathname}
        sidebarHeading="Companies"
        sidebarContent={sidebarContent}
        footer={footer}
      />

      {/* Main Area */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Top Header */}
        <header className="bg-white border-b border-gray-200 px-6 py-3.5 flex items-center justify-between flex-shrink-0 shadow-sm">
          <div>
            {breadcrumb && (
              <div className="flex items-center gap-1 text-sm text-gray-400 mb-0.5">
                {breadcrumb.map((item, idx) => (
                  <span key={idx} className="flex items-center gap-1">
                    {idx > 0 && <ChevronRight className="size-3" />}
                    {item.href ? (
                      <button
                        onClick={() => navigate(item.href!)}
                        className="hover:text-indigo-600 transition-colors"
                      >
                        {item.label}
                      </button>
                    ) : (
                      <span className="text-gray-700 font-medium">{item.label}</span>
                    )}
                  </span>
                ))}
              </div>
            )}
            {title && (
              <h1 className="text-gray-900 font-semibold">{title}</h1>
            )}
            {subtitle && (
              <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {actions && (
              <div className="flex items-center gap-2">
                {actions}
              </div>
            )}
          </div>
        </header>

        {/* Content */}
        <div className="flex-1 overflow-auto">
          {children}
        </div>
      </main>
    </div>
  );
}