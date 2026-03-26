import type { ReactNode } from "react";
import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  BarChart3, MessageSquare, Settings, Home,
  ChevronRight, HelpCircle, Bell, BarChart2
} from "lucide-react";
import { fetchCompanies, type CompanyInfo } from "../services/api";

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

  return (
    <div className="h-screen flex bg-slate-50 overflow-hidden">
      {/* Dark Sidebar */}
      <aside className="w-56 bg-slate-900 flex flex-col flex-shrink-0 shadow-xl">
        {/* Logo */}
        <div className="px-4 py-5 border-b border-slate-800">
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-3 w-full hover:opacity-90 transition-opacity"
          >
            <div className="size-9 rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center shadow-lg shadow-indigo-900/40 flex-shrink-0">
              <BarChart3 className="size-5 text-white" />
            </div>
            <div className="text-left min-w-0">
              <div className="text-white font-semibold tracking-tight">FinBot</div>
              <div className="text-slate-500 text-xs truncate">Financial Intelligence</div>
            </div>
          </button>
        </div>

        {/* Navigation */}
        <nav className="px-3 pt-4 pb-2 border-b border-slate-800">
          <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider px-2 mb-2">
            Menu
          </div>
          {navItems.map((item) => {
            const isActive =
              location.pathname === item.path ||
              (item.path !== "/" && location.pathname.startsWith(item.path));
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg mb-0.5 transition-all text-sm ${
                  isActive
                    ? "bg-indigo-600 text-white shadow-sm shadow-indigo-900/50"
                    : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
                }`}
              >
                <item.icon className="size-4 flex-shrink-0" />
                <span>{item.label}</span>
                {item.path === "/chat" && (
                  <span className="ml-auto bg-indigo-500 text-white text-xs px-1.5 py-0.5 rounded-full leading-none">
                    AI
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Companies */}
        <div className="flex-1 overflow-hidden px-3 pt-4">
          <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider px-2 mb-2">
            Companies
          </div>
          <div className="space-y-0.5 overflow-y-auto" style={{ maxHeight: "calc(100% - 28px)" }}>
            {companiesList.map((company) => {
              const isActive = location.pathname === `/company/${company.scrip_code}`;
              return (
                <button
                  key={company.scrip_code}
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
        </div>

        {/* Bottom User */}
        <div className="px-3 pb-4 pt-2 border-t border-slate-800">
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 cursor-pointer transition-colors">
            <div className="size-8 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center flex-shrink-0">
              <span className="text-white text-xs font-semibold">FA</span>
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-slate-300 text-sm truncate">Finance Analyst</div>
              <div className="text-xs text-slate-600 truncate">analyst@finbot.app</div>
            </div>
          </div>
        </div>
      </aside>

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
            <button className="size-8 rounded-lg flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors">
              <Bell className="size-4" />
            </button>
            <button className="size-8 rounded-lg flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors">
              <HelpCircle className="size-4" />
            </button>
            {actions && (
              <div className="flex items-center gap-2 ml-2 pl-2 border-l border-gray-200">
                {actions}
              </div>
            )}
          </div>
        </header>

        {/* Content */}
        <div className={`flex-1 overflow-auto ${noPadding ? "" : ""}`}>
          {children}
        </div>
      </main>
    </div>
  );
}