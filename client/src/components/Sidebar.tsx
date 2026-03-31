import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import type { LucideIcon } from "lucide-react";

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

  return (
    <aside className="w-56 bg-slate-900 flex flex-col flex-shrink-0 h-screen">
      <div className="px-4 py-5 border-b border-slate-800">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-3 w-full hover:opacity-90 transition-opacity"
        >
          <div className="size-9 rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center shadow-lg shadow-indigo-900/40 flex-shrink-0">
            <div className="size-5 text-white font-semibold">F</div>
          </div>
          <div className="text-left min-w-0">
            <div className="text-white font-semibold tracking-tight">FinBot</div>
            <div className="text-slate-500 text-xs truncate">Financial Intelligence</div>
          </div>
        </button>
      </div>

      {topAction && <div className="px-3 py-3 border-b border-slate-800">{topAction}</div>}

      <nav className="px-3 pt-4 pb-2 border-b border-slate-800">
        <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider px-2 mb-2">
          Pages
        </div>
        {navItems.map((item) => {
          const isActive =
            activePath === item.path ||
            (item.path !== "/" && activePath.startsWith(item.path));
          return (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg mb-0.5 transition-all text-sm ${
                isActive
                  ? "bg-indigo-600 text-white"
                  : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
              }`}
            >
              <item.icon className="size-4 flex-shrink-0" />
              <span>{item.label}</span>
              {item.badge && (
                <span className="ml-auto bg-indigo-500 text-white text-xs px-1.5 py-0.5 rounded-full leading-none">
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="flex-1 flex flex-col overflow-hidden px-3 pt-4">
        {sidebarHeading && (
          <div className="flex items-center justify-between px-2 mb-2">
            <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
              {sidebarHeading}
            </div>
            {headingAction && <div>{headingAction}</div>}
          </div>
        )}
        <div className="flex-1 overflow-y-auto space-y-0.5 pb-4">
          {sidebarContent}
        </div>
      </div>

      {footer && <div className="px-3 pb-4 pt-2 border-t border-slate-800">{footer}</div>}
    </aside>
  );
}
