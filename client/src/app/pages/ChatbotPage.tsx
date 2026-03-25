import { useState, useRef, useEffect, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Send, BarChart3, Plus, MessageSquare,
  Settings, Home, Search, Sparkles, Bot, User,
  TrendingUp, Building2, FileText, X
} from "lucide-react";
import { Button } from "../components/ui/button";
import { ChatMessage } from "../components/ChatMessage";
import type{ ChatMessage as ChatMessageType, processChatQuery } from "../data/chatbot";
import { companies } from "../data/companies";

const navItems = [
  { path: "/", icon: Home, label: "Home" },
  { path: "/chat", icon: MessageSquare, label: "Chat" },
  { path: "/admin", icon: Settings, label: "Admin" },
];

const suggestions = [
  { icon: TrendingUp, text: "Show financials for Reliance", color: "indigo" },
  { icon: Sparkles, text: "Generate report for Asian Paints", color: "purple" },
  { icon: Building2, text: "Show HDFC Bank key metrics", color: "orange" },
  { icon: TrendingUp, text: "What is WIPRO's 5Y PAT CAGR?", color: "blue" },
  { icon: FileText, text: "Compare HDFC and Reliance", color: "rose" },
];

const chatHistoryItems = [
  { id: 1, title: "Reliance Q3 Analysis", time: "2 hours ago", active: true },
  { id: 2, title: "HDFC Bank Credit Quality", time: "2 days ago" },
  { id: 3, title: "Asian Paints Margins", time: "3 days ago" },
  { id: 4, title: "Tech Sector Overview", time: "1 week ago" },
];

function TypingIndicator() {
  return (
    <div className="flex gap-3 items-start">
      <div className="size-8 rounded-lg bg-indigo-600 flex items-center justify-center flex-shrink-0 shadow-sm shadow-indigo-200">
        <Bot className="size-4 text-white" />
      </div>
      <div className="flex items-center gap-1.5 px-4 py-3 bg-white border border-gray-100 rounded-2xl rounded-tl-sm shadow-sm">
        <div className="size-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "0ms" }} />
        <div className="size-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "150ms" }} />
        <div className="size-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "300ms" }} />
      </div>
    </div>
  );
}

export default function ChatbotPage() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessageType[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "Hello! I'm **FinBot**, your AI-powered financial analysis assistant.\n\nI can help you with:\n• Company financials, KPIs & trends\n• Multi-company comparisons\n• AI-generated investment reports\n• XBRL data analysis\n\nTry asking: *\"Show financials for Reliance\"* or *\"Compare TCS and Infosys\"*",
      timestamp: new Date(),
    }
  ]);
  const [inputValue, setInputValue] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [currentChatId, setCurrentChatId] = useState(1);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [location] = useState(window.location.pathname);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const handleSendMessage = (content?: string) => {
    const text = content || inputValue;
    if (!text.trim()) return;

    const userMessage: ChatMessageType = {
      id: `msg-${Date.now()}-user`,
      role: "user",
      content: text,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMessage]);
    setInputValue("");
    setIsTyping(true);

    setTimeout(() => {
      setIsTyping(false);
      const aiResponse = processChatQuery(text, companies);
      setMessages(prev => [...prev, aiResponse]);
    }, 800 + Math.random() * 600);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleNewChat = () => {
    setMessages([
      {
        id: `welcome-${Date.now()}`,
        role: "assistant",
        content: "New conversation started! What would you like to analyze today?",
        timestamp: new Date(),
      }
    ]);
    setInputValue("");
  };

  return (
    <div className="min-h-screen w-full flex bg-slate-50 overflow-hidden">
      {/* ── Nav Rail ──────────────────────────────────────── */}
      <aside className="w-56 max-w-[280px] bg-slate-900 flex flex-col flex-shrink-0">
        {/* Logo */}
        <div className="px-4 py-5 border-b border-slate-800">
          <button onClick={() => navigate("/")} className="flex items-center gap-3">
            <div className="size-9 rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center shadow-lg shadow-indigo-900/40 flex-shrink-0">
              <BarChart3 className="size-5 text-white" />
            </div>
            <div>
              <div className="text-white font-semibold">FinBot</div>
              <div className="text-slate-500 text-xs">Financial Intelligence</div>
            </div>
          </button>
        </div>

        {/* New Chat */}
        <div className="px-3 py-3 border-b border-slate-800">
          <button
            onClick={handleNewChat}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors text-sm font-medium"
          >
            <Plus className="size-4" />
            New Chat
          </button>
        </div>

        {/* Nav */}
        <div className="px-3 py-3 border-b border-slate-800">
          <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider px-2 mb-1.5">Pages</div>
          {navItems.map((item) => {
            const isActive = item.path === "/chat";
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg mb-0.5 transition-all text-sm ${
                  isActive
                    ? "bg-indigo-600 text-white"
                    : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
                }`}
              >
                <item.icon className="size-4" />
                {item.label}
              </button>
            );
          })}
        </div>

        {/* Chat History */}
        <div className="flex-1 overflow-hidden px-3 py-3">
          <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider px-2 mb-1.5">
            Recent Chats
          </div>
          <div className="space-y-0.5 overflow-y-auto" style={{ maxHeight: "calc(100% - 24px)" }}>
            {chatHistoryItems.map((chat) => (
              <button
                key={chat.id}
                onClick={() => setCurrentChatId(chat.id)}
                className={`w-full text-left px-3 py-2.5 rounded-lg transition-all group ${
                  currentChatId === chat.id
                    ? "bg-slate-700 text-white"
                    : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
                }`}
              >
                <div className="text-sm truncate font-medium">{chat.title}</div>
                <div className="text-xs text-slate-600 mt-0.5">{chat.time}</div>
              </button>
            ))}
          </div>
        </div>

        {/* User */}
        <div className="px-3 pb-4 pt-2 border-t border-slate-800">
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-400 hover:bg-slate-800 cursor-pointer transition-colors">
            <div className="size-8 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center flex-shrink-0">
              <span className="text-white text-xs font-semibold">FA</span>
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-slate-300 text-sm truncate">Finance Analyst</div>
              <div className="text-xs text-slate-600 truncate">Free Plan</div>
            </div>
          </div>
        </div>
      </aside>

      {/* ── Chat Area ─────────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0 bg-slate-50">
        {/* Header */}
        <header className="bg-white border-b px-6 py-3.5 flex items-center justify-between flex-shrink-0 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="size-8 rounded-full bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center">
              <Bot className="size-4 text-white" />
            </div>
            <div>
              <div className="font-semibold text-gray-900 text-sm">FinBot Assistant</div>
              <div className="flex items-center gap-1.5 text-xs text-emerald-500">
                <div className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Online · XBRL data active
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors">
              <Search className="size-4" />
              Search
            </button>
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.map((message) => (
              <ChatMessage key={message.id} message={message} />
            ))}
            {isTyping && <TypingIndicator />}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Suggestions (only when fresh) */}
        {messages.length === 1 && !isTyping && (
          <div className="px-6 pb-4">
            <div className="max-w-3xl mx-auto">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-3 font-medium">Suggested queries</p>
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
                {suggestions.map((s, idx) => {
                  const colorClass: Record<string, string> = {
                    indigo: "border-indigo-100 hover:border-indigo-300 hover:bg-indigo-50",
                    purple: "border-purple-100 hover:border-purple-300 hover:bg-purple-50",
                    orange: "border-orange-100 hover:border-orange-300 hover:bg-orange-50",
                    blue: "border-blue-100 hover:border-blue-300 hover:bg-blue-50",
                    rose: "border-rose-100 hover:border-rose-300 hover:bg-rose-50",
                  };
                  const iconColorClass: Record<string, string> = {
                    indigo: "text-indigo-500",
                    purple: "text-purple-500",
                    orange: "text-orange-500",
                    blue: "text-blue-500",
                    rose: "text-rose-500",
                  };
                  return (
                    <button
                      key={idx}
                      onClick={() => handleSendMessage(s.text)}
                      className={`flex items-center gap-2.5 text-left px-4 py-3 bg-white border rounded-xl text-sm text-gray-700 hover:text-gray-900 transition-all ${colorClass[s.color]}`}
                    >
                      <s.icon className={`size-4 flex-shrink-0 ${iconColorClass[s.color]}`} />
                      <span>{s.text}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Input */}
        <div className="bg-white border-t px-6 py-4 flex-shrink-0">
          <div className="max-w-3xl mx-auto">
            <div className="flex gap-3 items-end bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm focus-within:border-indigo-300 focus-within:shadow-md transition-all">
              <textarea
                ref={inputRef}
                rows={1}
                placeholder="Ask about companies, financials, comparisons..."
                value={inputValue}
                onChange={(e) => {
                  setInputValue(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
                }}
                onKeyDown={handleKeyDown}
                className="flex-1 resize-none outline-none text-sm text-gray-900 placeholder-gray-400 bg-transparent min-h-[24px] max-h-[120px] leading-6"
                style={{ height: "24px" }}
              />
              <button
                onClick={() => handleSendMessage()}
                disabled={!inputValue.trim() || isTyping}
                className={`size-8 rounded-xl flex items-center justify-center flex-shrink-0 transition-all ${
                  inputValue.trim() && !isTyping
                    ? "bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm shadow-indigo-200"
                    : "bg-gray-100 text-gray-400 cursor-not-allowed"
                }`}
              >
                <Send className="size-4" />
              </button>
            </div>
            <p className="text-xs text-gray-400 text-center mt-2">
              FinBot uses XBRL-structured data. Results are for research purposes only.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}