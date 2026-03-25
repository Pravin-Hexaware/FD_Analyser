import * as React from "react";
import type{ ChatMessage as ChatMessageType } from "../data/chatbot";
import { CompanyInfoCard } from "./CompanyInfoCard";
import { FinancialTable } from "./FinancialTable";
import { ComparisonTable } from "./ComparisonTable";
import { User, Bot } from "lucide-react";

interface ChatMessageProps {
  message: ChatMessageType;
}

function renderContent(text: string) {
  // Simple markdown-ish formatting
  const lines = text.split("\n");
  return lines.map((line, i) => {
    // Bold **text**
    let rendered: React.ReactNode = line
      .split(/(\*\*[^*]+\*\*)/g)
      .map((part, j) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={j} className="font-semibold">{part.slice(2, -2)}</strong>;
        }
        // Italic *text*
        return part.split(/(\*[^*]+\*)/g).map((p, k) => {
          if (p.startsWith("*") && p.endsWith("*") && p.length > 2) {
            return <em key={k} className="italic text-indigo-600">{p.slice(1, -1)}</em>;
          }
          return p;
        });
      });

    if (line.startsWith("• ")) {
      return (
        <div key={i} className="flex items-start gap-2 my-0.5">
          <span className="text-indigo-400 mt-0.5">•</span>
          <span>{rendered}</span>
        </div>
      );
    }

    if (line === "") return <div key={i} className="h-2" />;
    return <div key={i}>{rendered}</div>;
  });
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div
        className={`size-8 rounded-lg flex items-center justify-center flex-shrink-0 shadow-sm ${
          isUser ? "bg-gray-200" : "bg-indigo-600 shadow-indigo-200"
        }`}
      >
        {isUser ? (
          <User className="size-4 text-gray-600" />
        ) : (
          <Bot className="size-4 text-white" />
        )}
      </div>

      {/* Content */}
      <div className={`flex flex-col gap-2 max-w-[85%] ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`px-4 py-3 text-sm leading-relaxed ${
            isUser
              ? "bg-indigo-600 text-white rounded-2xl rounded-tr-sm shadow-sm shadow-indigo-200"
              : "bg-white border border-gray-100 rounded-2xl rounded-tl-sm shadow-sm text-gray-800"
          }`}
        >
          {isUser ? (
            <span>{message.content}</span>
          ) : (
            <div className="space-y-0.5">{renderContent(message.content)}</div>
          )}
        </div>

        {/* Widget */}
        {message.widget && !isUser && (
          <div className="w-full mt-1 max-w-2xl">
            {message.widget.type === "company-card" && (
              <CompanyInfoCard companyId={message.widget.companyId} />
            )}
            {message.widget.type === "financial-table" && (
              <FinancialTable
                companyId={message.widget.companyId}
                years={message.widget.years}
              />
            )}
            {message.widget.type === "comparison-table" && (
              <ComparisonTable companyIds={message.widget.companyIds} />
            )}
          </div>
        )}

        <span className="text-xs text-gray-400 px-1">
          {message.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
    </div>
  );
}
