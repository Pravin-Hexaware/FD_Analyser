import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type{ ChatMessage as ChatMessageType } from "../data/chatbot";
import { CompanyInfoCard } from "./CompanyInfoCard";
import { FinancialTable } from "./FinancialTable";
import { ComparisonTable } from "./ComparisonTable";
import { User, Bot } from "lucide-react";

interface ChatMessageProps {
  message: ChatMessageType;
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
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
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
