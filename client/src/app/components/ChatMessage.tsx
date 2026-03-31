import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import pdfMake from 'pdfmake/build/pdfmake';
import 'pdfmake/build/vfs_fonts';
import type{ ChatMessage as ChatMessageType } from "../data/chatbot";
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
    const table = {
      style: 'table',
      table: {
        headerRows: 1,
        widths: tableRows[0].map(() => 'auto'),
        body: tableRows
      },
      layout: {
        hLineWidth: () => 0.5,
        vLineWidth: () => 0.5,
        hLineColor: () => '#ccc',
        vLineColor: () => '#ccc',
        paddingLeft: () => 5,
        paddingRight: () => 5,
        paddingTop: () => 3,
        paddingBottom: () => 3
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
        const table = {
          style: 'table',
          table: {
            headerRows: 1,
            widths: tableRows[0].map(() => 'auto'),
            body: tableRows
          },
          layout: {
            hLineWidth: () => 0.5,
            vLineWidth: () => 0.5,
            hLineColor: () => '#ccc',
            vLineColor: () => '#ccc',
            paddingLeft: () => 5,
            paddingRight: () => 5,
            paddingTop: () => 3,
            paddingBottom: () => 3
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
    defaultStyle: {
      fontSize: 14,
      lineHeight: 1.6
    },
    styles: {
      header1: { fontSize: 24, bold: true, margin: [0, 10, 0, 8] },
      header2: { fontSize: 20, bold: true, margin: [0, 8, 0, 6] },
      header3: { fontSize: 16, bold: true, margin: [0, 6, 0, 4] },
      table: { margin: [0, 5, 0, 10] }
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

export function ChatMessage({ message }: ChatMessageType) {
  const isUser = message.role === "user";

  const handleDownload = () => {
    const docDefinition = markdownToPdfmake(message.content);
    pdfMake.createPdf(docDefinition).download(`chat-${message.id}.pdf`);
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
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
            <>
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </div>
              <div className="flex items-center gap-3 mt-3 pt-2 border-t border-gray-100">
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors"
                  title="Copy response"
                >
                  <Copy className="size-3" />
                  Copy
                </button>
                <button
                  onClick={handleDownload}
                  className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors"
                  title="Download as PDF"
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
