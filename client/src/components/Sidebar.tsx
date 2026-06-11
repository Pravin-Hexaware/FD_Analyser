import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useSidebarContext } from "../context/SidebarContext";
import logo from "../assets/logo.jpg";

interface SidebarNavItem {
  path: string;
  icon: LucideIcon;
  label: string;
  badge?: string;
}

interface SidebarProps {
  navItems: SidebarNavItem[];
  activePath: string;
  sidebarHeading?: string;
  headingAction?: ReactNode;
  sidebarContent?: ReactNode;
  topAction?: ReactNode;
  footer?: ReactNode;
}

export function Sidebar({
  navItems,
  activePath,
  sidebarHeading,
  headingAction,
  sidebarContent,
  topAction,
  footer,
}: SidebarProps) {
  const navigate = useNavigate();
  const { isCollapsed, setIsCollapsed } = useSidebarContext();

  return (
    <aside className={`${isCollapsed ? 'w-16' : 'w-56'} bg-slate-900 flex flex-col flex-shrink-0 h-screen transition-all duration-300 ease-in-out relative`}>
      {/* Collapse/Expand Toggle Button */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="absolute -right-3 top-6 z-10 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-full p-1.5 shadow-lg transition-colors"
        title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {isCollapsed ? (
          <ChevronRight className="size-3 text-slate-400" />
        ) : (
          <ChevronLeft className="size-3 text-slate-400" />
        )}
      </button>

      <div className="px-4 py-5 border-b border-slate-800">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-3 w-full hover:opacity-90 transition-opacity"
        >
          <img
            src={logo}
            alt="Logo"
            className={`transition-all duration-200 ${isCollapsed ? 'h-8 w-8' : 'h-10 w-10'}`}
          />
          {!isCollapsed && (
            <div className="text-left min-w-0">
              <div className="text-white font-semibold tracking-tight">FinBot</div>
              <div className="text-slate-500 text-xs truncate">Financial Intelligence</div>
            </div>
          )}
        </button>
      </div>

      {topAction && <div className={`${isCollapsed ? 'px-2' : 'px-3'} py-3 border-b border-slate-800`}>{topAction}</div>}

      <nav className={`${isCollapsed ? 'px-2' : 'px-3'} pt-4 pb-2 border-b border-slate-800`}>
        {!isCollapsed && (
          <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider px-2 mb-2">
            Pages
          </div>
        )}
        {navItems.map((item) => {
          const isActive =
            activePath === item.path ||
            (item.path !== "/" && activePath.startsWith(item.path));
          return (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={`w-full flex items-center ${isCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} py-2.5 rounded-lg mb-0.5 transition-all text-sm ${
                isActive
                  ? "bg-indigo-600 text-white"
                  : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
              }`}
              title={isCollapsed ? item.label : undefined}
            >
              <item.icon className="size-4 flex-shrink-0" />
              {!isCollapsed && <span>{item.label}</span>}
              {item.badge && !isCollapsed && (
                <span className="ml-auto bg-indigo-500 text-white text-xs px-1.5 py-0.5 rounded-full leading-none">
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className={`flex-1 flex flex-col overflow-hidden ${isCollapsed ? 'px-2' : 'px-3'} pt-4`}>
        {sidebarHeading && (
          <div className={`flex items-center justify-between ${isCollapsed ? 'px-1' : 'px-2'} mb-2`}>
            {!isCollapsed && (
              <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
                {sidebarHeading}
              </div>
            )}
            {headingAction && <div>{headingAction}</div>}
          </div>
        )}
        <div className="flex-1 overflow-y-auto space-y-0.5 pb-4">
          {sidebarContent}
        </div>
      </div>

      {footer && <div className={`${isCollapsed ? 'px-2' : 'px-3'} pb-4 pt-2 border-t border-slate-800`}>{footer}</div>}
    </aside>
  );
}
