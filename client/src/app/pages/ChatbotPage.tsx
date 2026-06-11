import { useState, useRef, useEffect, type KeyboardEvent } from "react";
import { useLocation } from "react-router-dom";
import {
  Send, Plus, MessageSquare,
  Settings, Home, Sparkles, Bot,
  TrendingUp, Building2, FileText
} from "lucide-react";
import { ChatMessage } from "../components/ChatMessage";
import { CompactProgressCard } from "../components/CompactProgressCard";
import { Sidebar } from "../../components/Sidebar";
import { useSidebarContext } from "../../context/SidebarContext";
import type { ChatMessage as ChatMessageType } from "../data/chatbot";
import { processChatQuery } from "../data/chatbot";
import { companies } from "../data/companies";
import { fetchChatHistory, fetchChat, type ChatHistoryItem } from "../services/api";

const navItems = [
  { path: "/", icon: Home, label: "Dashboard" },
  { path: "/chat", icon: MessageSquare, label: "AI Chat", badge: "AI" },
  { path: "/compare", icon: TrendingUp, label: "Compare" },
  { path: "/admin", icon: Settings, label: "Admin" },
];

const suggestions = [
  { icon: TrendingUp, text: "Show financials for Reliance", color: "indigo" },
  { icon: Sparkles, text: "Generate report for Asian Paints", color: "purple" },
  { icon: Building2, text: "Show HDFC Bank key metrics", color: "orange" },
  { icon: TrendingUp, text: "What is WIPRO's 5Y PAT CAGR?", color: "blue" },
  { icon: FileText, text: "Compare HDFC and ICICI", color: "rose" },
];

export default function ChatbotPage() {
  const location = useLocation();
  const { isCollapsed } = useSidebarContext();
  const [messages, setMessages] = useState<ChatMessageType[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "Hello! I'm **FinBot**, your AI-powered financial analysis assistant.\n\nI can help you with:\n• Company financials, KPIs & trends\n• Multi-company comparisons\n• AI-generated investment reports\n• Financial data analysis\n\nTry asking: *\"Show financials for Reliance\"* or *\"Compare TCS and Infosys\"*",
      timestamp: new Date(),
    }
  ]);
  const [inputValue, setInputValue] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [isResponseComplete, setIsResponseComplete] = useState(false);
  const [currentChatId, setCurrentChatId] = useState<number | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatHistoryItem[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Load chat history on component mount
  useEffect(() => {
    loadChatHistory();
  }, []);

  const loadChatHistory = async () => {
    try {
      const history = await fetchChatHistory();
      setChatHistory(history);
    } catch (error) {
      console.warn("Failed to load chat history:", error);
    }
  };

  const loadChatById = async (chatId: string) => {
    try {
      const conversation = await fetchChat(chatId);
      setCurrentChatId(Number(conversation.chat_id));

      const loadedMessages: ChatMessageType[] = conversation.messages.map((msg) => ({
        id: `msg-${conversation.chat_id}-${msg.id}`,
        role: msg.role as "user" | "assistant",
        content: msg.content,
        timestamp: new Date(msg.created_at.includes("Z") ? msg.created_at : msg.created_at.replace(" ", "T") + "Z"),
      }));

      setMessages(loadedMessages);
      setIsResponseComplete(false);
    } catch (error) {
      console.warn("Failed to load chat:", error);
    }
  };

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
    setIsResponseComplete(false);

    // Call the async function to process the query
    processChatQuery(text, companies, currentChatId ?? undefined)
      .then((response) => {
        setIsTyping(false);
        setIsResponseComplete(true);
        setMessages(prev => [...prev, response.message]);
        if (response.conversationId) {
          setCurrentChatId(response.conversationId);
        }
        loadChatHistory();
      })
      .catch(error => {
        console.error("Error processing chat query:", error);
        setIsTyping(false);
        setIsResponseComplete(true);
        // Don't show error message, just log the error
      });
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleNewChat = () => {
    setCurrentChatId(null);
    setMessages([
      {
        id: `welcome-${Date.now()}`,
        role: "assistant",
        content: "New conversation started! What would you like to analyze today?",
        timestamp: new Date(),
      }
    ]);
    setInputValue("");
    setIsResponseComplete(false);
  };

  const formatToIST = (value: string) => {
    const normalized = value.includes(" ") && !value.endsWith("Z") ? value.replace(" ", "T") + "Z" : value;
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return new Intl.DateTimeFormat("en-IN", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "Asia/Kolkata",
    }).format(date);
  };

  const sidebarContent = (
    <>
      {chatHistory.length === 0 ? (
        <div className="text-xs text-slate-500 px-3 py-2">No chats yet</div>
      ) : (
        chatHistory.map((chat) => (
          <button
            key={chat.chat_id}
            onClick={() => loadChatById(chat.chat_id)}
            className={`w-full text-left px-3 py-2.5 rounded-lg transition-all group ${
              currentChatId === Number(chat.chat_id)
                ? "bg-slate-700 text-white"
                : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
            }`}
          >
            <div className="text-sm truncate font-medium">{chat.title}</div>
            <div className="text-xs text-slate-400 mt-0.5">{formatToIST(chat.created_at)}</div>
          </button>
        ))
      )}
    </>
  );

  const sidebarFooter = (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-400 hover:bg-slate-800 cursor-pointer transition-colors">
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
        sidebarHeading={isCollapsed ? undefined : "Recent Chats"}
        headingAction={isCollapsed ? null : (
          <button
            onClick={handleNewChat}
            className="size-8 rounded-lg flex items-center justify-center text-slate-300 hover:text-white hover:bg-slate-700 transition-colors"
            title="New Chat"
          >
            <Plus className="size-4" />
          </button>
        )}
        sidebarContent={!isCollapsed && sidebarContent}
        footer={sidebarFooter}
      />

      {/* ── Chat Area ─────────────────────────────────────── */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden bg-slate-50">
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
                Online · Ready to analyze financials!
              </div>
            </div>
          </div>
          {/*<div className="flex items-center gap-2">
            <button className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors">
              <Search className="size-4" />
              Search
            </button>
          </div> */}
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.map((message) => (
              <ChatMessage key={message.id} message={message} />
            ))}
            {isTyping && !isResponseComplete && (
              <CompactProgressCard 
                isLoading={isTyping} 
                isResponseComplete={isResponseComplete}
              />
            )}

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
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input */}
        <div className="bg-slate-50 px-6 py-4 flex-shrink-0">
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
                className="flex-1 resize-none outline-none text-sm text-gray-900 placeholder-gray-400 bg-transparent min-h-[24px] max-h-[120px] leading-6 overflow-y-auto overflow-x-hidden hide-scrollbar"
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