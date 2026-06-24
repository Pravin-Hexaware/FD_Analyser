import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from 'rehype-sanitize';
import pdfMake from 'pdfmake/build/pdfmake';
import 'pdfmake/build/vfs_fonts';
import { toast } from 'react-hot-toast';
import type { ChatMessage as ChatMessageType } from "../data/chatbot";
import { CompanyInfoCard } from "./CompanyInfoCard";
import { FinancialTable } from "./FinancialTable";
import { ComparisonTable } from "./ComparisonTable";
import { User, Bot, Download, Copy } from "lucide-react";

interface ChatMessageProps {
  message: ChatMessageType;
}

function markdownToPdfmake(markdown: string) {
  const lines = markdown.split('\n');
  const content: any[] = [];
  let inTable = false;
  let tableRows: string[][] = [];
  let tableColumns = 0;

  function endTable() {
  if (tableRows.length > 1) {
    // Calculate dynamic widths based on content
    const numCols = tableRows[0].length;
    const colWidths: number[] = [];
    for (let i = 0; i < numCols; i++) {
      let maxLen = 0;
      for (const row of tableRows) {
        if (row[i]) {
          maxLen = Math.max(maxLen, row[i].length);
        }
      }
      colWidths[i] = maxLen * 3; // Approximate width per character
    }
    const totalWidth = colWidths.reduce((sum, w) => sum + w, 0);
    const scale = totalWidth > 550 ? 550 / totalWidth : 1;
    const finalWidths = colWidths.map(w => w * scale);

    const table = {
      style: 'table',
      table: {
        headerRows: 1,
        widths: finalWidths,
        body: tableRows
      },
      layout: {
        hLineWidth: () => 0.5,
        vLineWidth: () => 0.5,
        hLineColor: () => '#ccc',
        vLineColor: () => '#ccc',
        paddingLeft: () => 2,
        paddingRight: () => 2,
        paddingTop: () => 2,
        paddingBottom: () => 2
      }
    };
    content.push(table);
  }
    inTable = false;
    tableRows = [];
    tableColumns = 0;
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line === '') continue;

    if (line.startsWith('# ')) {
      content.push({ text: line.substring(2), style: 'header1' });
    } else if (line.startsWith('## ')) {
      content.push({ text: line.substring(3), style: 'header2' });
    } else if (line.startsWith('### ')) {
      content.push({ text: line.substring(4), style: 'header3' });
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      // Parse markdown in list items
      const parsed = parseTextWithFormatting(line.substring(2));
      content.push({ text: [{ text: '• ', bold: false }, ...Array.isArray(parsed) ? parsed : [{ text: parsed }]], margin: [10, 2, 0, 2] });
    } else if (line.includes('|') && line.split('|').length > 2) {
      // Standard markdown table with | separators
      const cells = line.split('|').map(cell => cell.trim()).filter(cell => cell !== '');
      if (!inTable) {
        inTable = true;
        tableColumns = cells.length;
        tableRows = [];
      }
      // Ensure row has the correct number of columns
      while (cells.length < tableColumns) {
        cells.push('');
      }
      if (cells.length > tableColumns) {
        cells.splice(tableColumns);
      }
      tableRows.push(cells);
    } else {
      if (inTable) {
        // End table
        if (tableRows.length > 1) { // Need at least header + 1 data row
          // Calculate dynamic widths based on content
          const numCols = tableRows[0].length;
          const colWidths: number[] = [];
          for (let i = 0; i < numCols; i++) {
            let maxLen = 0;
            for (const row of tableRows) {
              if (row[i]) {
                maxLen = Math.max(maxLen, row[i].length);
              }
            }
            colWidths[i] = maxLen * 2; // Approximate width per character
          }
          const totalWidth = colWidths.reduce((sum, w) => sum + w, 0);
          const scale = totalWidth > 500 ? 500 / totalWidth : 1;
          const finalWidths = colWidths.map(w => w * scale);

          const table = {
            style: 'table',
            table: {
              headerRows: 1,
              widths: finalWidths,
              body: tableRows
            },
            layout: {
              hLineWidth: () => 0.5,
              vLineWidth: () => 0.5,
              hLineColor: () => '#ccc',
              vLineColor: () => '#ccc',
              paddingLeft: () => 2,
              paddingRight: () => 2,
              paddingTop: () => 2,
              paddingBottom: () => 2
            }
          };
          content.push(table);
        }
        inTable = false;
        tableRows = [];
        tableColumns = 0;
      }
      // regular text
      const textObj = parseTextWithFormatting(line);
      content.push({ text: textObj, margin: [0, 2, 0, 2] });
    }
  }

  return {
    content,
    pageMargins: [40, 60, 40, 60],
    defaultStyle: {
      fontSize: 10,
      lineHeight: 1.6
    },
    styles: {
      header1: { fontSize: 18, bold: true, margin: [0, 10, 0, 8] },
      header2: { fontSize: 16, bold: true, margin: [0, 8, 0, 6] },
      header3: { fontSize: 14, bold: true, margin: [0, 6, 0, 4] },
      table: { margin: [0, 5, 0, 10], fontSize: 6 }
    }
  };
}

function parseTextWithFormatting(text: string): any[] {
  // Improved markdown bold/italic parser for **bold**, *italic*, and ***bold italic***
  const parts: any[] = [];
  let i = 0;
  let current = '';
  let bold = false;
  let italic = false;
  while (i < text.length) {
    // Handle ***bold italic***
    if (text.startsWith('***', i)) {
      if (current) {
        parts.push({ text: current, bold, italics: italic });
        current = '';
      }
      bold = !bold;
      italic = !italic;
      i += 3;
      continue;
    }
    // Handle **bold**
    if (text.startsWith('**', i)) {
      if (current) {
        parts.push({ text: current, bold, italics: italic });
        current = '';
      }
      bold = !bold;
      i += 2;
      continue;
    }
    // Handle *italic*
    if (text.startsWith('*', i)) {
      if (current) {
        parts.push({ text: current, bold, italics: italic });
        current = '';
      }
      italic = !italic;
      i += 1;
      continue;
    }
    current += text[i];
    i++;
  }
  if (current) {
    parts.push({ text: current, bold, italics: italic });
  }
  // If no formatting, return as simple text
  if (parts.length === 1 && !parts[0].bold && !parts[0].italics) {
    return parts[0].text;
  }
  return parts;
}

function ChatMessageComponent({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  const normalizeFileName = (text: string) => {
    const cleaned = text
      .replace(/^[#_*\s]+/, "")
      .replace(/[\/:*?"<>|]/g, "")
      .replace(/_+/g, " ")
      .replace(/\s+/g, " ")
      .replace(/^[#_*\s]+|[#_*\s]+$/g, "")
      .trim();
    if (!cleaned) {
      return `FinBot-response-${message.id}`;
    }
    const words = cleaned.split(" ").slice(0, 8).join(" ");
    return words;
  };

  const extractTitleCandidate = (content: string): string => {
    const lines = content.split("\n").map((line) => line.trim()).filter(Boolean);
    if (lines.length === 0) {
      return message.id;
    }

    const prefixPattern = /^(?:#+\s*)?comprehensive financial analysis report\s*[:\-]?\s*/i;

    // Prefer the first non-empty line that is not just the standard report heading.
    for (let i = 0; i < lines.length; i += 1) {
      let line = lines[i].replace(/^[#_*\s]+/, "");
      if (!prefixPattern.test(line)) {
        return line;
      }
      const stripped = line.replace(prefixPattern, "").replace(/^[#_*\s]+/, "").trim();
      if (stripped) {
        return stripped;
      }
      if (i + 1 < lines.length) {
        return lines[i + 1].replace(/^[#_*\s]+/, "");
      }
    }

    return lines[0].replace(prefixPattern, "").replace(/^[#_*\s]+/, "").trim() || message.id;
  };

  const handleDownload = () => {
    const docDefinition = markdownToPdfmake(message.content);
    const titleSource = message.title?.trim() || extractTitleCandidate(message.content);
    const fileName = normalizeFileName(titleSource);
    pdfMake.createPdf(docDefinition).download(`${fileName}.pdf`);
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      toast.success("Response Copied");
    } catch (error) {
      toast.error("Copy failed");
      console.error("Copy failed", error);
    }
  };

  const markdownComponents = {
    table: ({ node, ...props }: any) => (
      <div className="scrollable-markdown-table overflow-x-auto rounded-lg bg-slate-50/50 p-0.5">
        <table className="min-w-max" {...props} />
      </div>
    ),
  };

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
      <div className={`flex flex-col gap-2 min-w-0 ${isUser ? "max-w-[85%] items-end" : "flex-1 w-full items-start"}`}>
        <div
          className={`px-4 py-3 text-sm leading-relaxed min-w-0 overflow-hidden ${
            isUser
              ? "bg-indigo-600 text-white rounded-2xl rounded-tr-sm shadow-sm shadow-indigo-200"
              : "w-full bg-white border border-gray-100 rounded-2xl rounded-tl-sm shadow-sm text-gray-800"
          }`}
        >
          {isUser ? (
            <span>{message.content}</span>
          ) : (
            <>
              <div className="prose prose-sm max-w-full">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypeSanitize]}
                  components={markdownComponents}
                >
                  {message.content}
                </ReactMarkdown>
              </div>
              <div className="flex items-center gap-3 mt-3 pt-2 border-t border-gray-100">
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors bg-transparent border-none p-0 outline-none focus:outline-none"
                  title="Copy response"
                  type="button"
                >
                  <Copy className="size-3" />
                  Copy
                </button>
                <button
                  onClick={handleDownload}
                  className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors bg-transparent border-none p-0 outline-none focus:outline-none"
                  title="Download as PDF"
                  type="button"
                >
                  <Download className="size-3" />
                  Download
                </button>
              </div>
            </>
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

        <div className="flex items-center gap-2 px-1">
          <span className="text-xs text-gray-400">
            {new Intl.DateTimeFormat("en-IN", {
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
              timeZone: "Asia/Kolkata",
            }).format(new Date(message.timestamp))}
          </span>
        </div>
      </div>
    </div>
  );
}

export const ChatMessage = React.memo(ChatMessageComponent, (prevProps, nextProps) => {
  return prevProps.message.id === nextProps.message.id
    && prevProps.message.content === nextProps.message.content
    && prevProps.message.role === nextProps.message.role
    && prevProps.message.timestamp.getTime() === nextProps.message.timestamp.getTime();
});
