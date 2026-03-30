import React, { createContext, useContext, useState, useRef, useCallback } from "react";
import type { ReactNode } from "react";

interface ExtractionContextType {
  isCollecting: boolean;
  isExtractingData: boolean;
  liveLog: string[];
  logs: any[];
  startXbrlExtraction: () => Promise<void>;
  startDataExtraction: () => Promise<void>;
  stopExtraction: () => void;
  addLiveLog: (text: string) => void;
  addLog: (log: any) => void;
  clearLiveLog: () => void;
  clearLogs: () => void;
  wsRef: React.MutableRefObject<WebSocket | null>;
  onCompanyExtracted?: (company: any) => void;
  setOnCompanyExtracted?: (callback: (company: any) => void) => void;
}

const ExtractionContext = createContext<ExtractionContextType | undefined>(undefined);

export const ExtractionProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [isCollecting, setIsCollecting] = useState(false);
  const [isExtractingData, setIsExtractingData] = useState(false);
  const [liveLog, setLiveLog] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem("adminLiveLog");
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });
  const [logs, setLogs] = useState<any[]>(() => {
    try {
      const saved = localStorage.getItem("adminLogs");
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  const wsRef = useRef<WebSocket | null>(null);
  const onCompanyExtractedRef = useRef<((company: any) => void) | undefined>(undefined);

  const setOnCompanyExtracted = useCallback((callback: (company: any) => void) => {
    onCompanyExtractedRef.current = callback;
  }, []);

  // Persist live logs to localStorage
  const persistLiveLog = useCallback((newLog: string[]) => {
    localStorage.setItem("adminLiveLog", JSON.stringify(newLog));
  }, []);

  // Persist logs to localStorage
  const persistLogs = useCallback((newLogs: any[]) => {
    localStorage.setItem("adminLogs", JSON.stringify(newLogs));
  }, []);

  const addLiveLog = useCallback((text: string) => {
    const newLine = `[${new Date().toLocaleTimeString()}] ${text}`;
    setLiveLog((prev) => {
      const updated = [...prev, newLine];
      persistLiveLog(updated);
      return updated;
    });
  }, [persistLiveLog]);

  const addLog = useCallback((log: any) => {
    setLogs((prev) => {
      const updated = [log, ...prev];
      persistLogs(updated);
      return updated;
    });
  }, [persistLogs]);

  const clearLiveLog = useCallback(() => {
    setLiveLog([]);
    persistLiveLog([]);
  }, [persistLiveLog]);

  const clearLogs = useCallback(() => {
    setLogs([]);
    persistLogs([]);
  }, [persistLogs]);

  const connectWebSocket = useCallback(
    (endpoint: "fetch" | "extract"): Promise<WebSocket> => {
      return new Promise((resolve, reject) => {
        const wsEndpoint =
          endpoint === "fetch"
            ? "ws://localhost:8001/api/ws/xbrl-fetch-latest"
            : "ws://localhost:8001/api/ws/xbrl-extract-from-db";

        const ws = new WebSocket(wsEndpoint);
        
        // Set a timeout for connection
        const timeout = setTimeout(() => {
          ws.close();
          reject(new Error(`Connection timeout - Is backend server running on port 8001?`));
        }, 5000);

        ws.onopen = () => {
          clearTimeout(timeout);
          addLiveLog(`✓ Connected to ${endpoint} service`);
          resolve(ws);
        };

        ws.onerror = () => {
          clearTimeout(timeout);
          const errorMsg = "Backend server not responding on ws://localhost:8001";
          addLiveLog(`✗ Connection error: ${errorMsg}`);
          reject(new Error(errorMsg));
        };
      });
    },
    [addLiveLog]
  );

  const startXbrlExtraction = useCallback(async () => {
    setIsCollecting(true);
    clearLiveLog();
    addLiveLog("Initializing XBRL fetch pipeline...");

    try {
      const ws = await connectWebSocket("fetch");
      wsRef.current = ws;

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.status === "starting") {
          addLiveLog("Pipeline started, reading CSV file...");
        } else if (data.status === "read_csv") {
          addLiveLog(`✓ Read ${data.records} companies from CSV`);
        } else if (data.status === "resume_from") {
          addLiveLog(`Resuming from company index: ${data.start_idx}`);
        } else if (data.status === "skipped") {
          addLiveLog(`⊘ Skipped company at index ${data.idx}: ${data.reason}`);
        } else if (data.status === "already_found_in_db") {
          addLiveLog(`⊘ ${data.scrip_code} - already found in db, skipping`);
        } else if (data.report_type && data.period) {
          const typeLabel = data.report_type === "annual" ? "📊" : "📄";
          const logMessage = `${typeLabel} ${data.symbol} (${data.scrip_code}) → ${data.report_type}: ${data.period} ${data.stored ? "[Stored]" : "[New]"}`;
          addLiveLog(logMessage);
          
          // Add individual company to Recent Runs
          if (data.stored) {
            const companyLog = {
              id: String(Date.now() + Math.random()),
              company: `${data.symbol} (${data.scrip_code})`,
              status: "success" as const,
              timestamp: new Date(),
              recordsProcessed: 1,
              message: `${data.report_type}: ${data.period}`,
            };
            addLog(companyLog);
          }
        } else if (data.status === "complete") {
          addLiveLog("✓ XBRL fetch complete!");
          setIsCollecting(false);

          const newLog = {
            id: String(logs.length + 1),
            company: "All Companies (XBRL Fetch)",
            status: "success",
            timestamp: new Date(),
            recordsProcessed: 1440,
            message: "XBRL URLs fetched and stored",
          };
          addLog(newLog);
          ws.close();
          wsRef.current = null;
        } else if (data.error) {
          addLiveLog(`✗ Error: ${data.error}`);
        }
      };

      ws.onerror = () => {
        setIsCollecting(false);
        addLiveLog("✗ WebSocket connection error");
      };

      ws.onclose = () => {
        if (isCollecting) {
          addLiveLog("⟳ Connection closed (extraction may still be running on server)");
        }
      };
    } catch (error) {
      setIsCollecting(false);
      const errorMsg = error instanceof Error ? error.message : String(error);
      addLiveLog(`✗ Failed to connect: ${errorMsg}`);
    }
  }, [connectWebSocket, addLiveLog, clearLiveLog, logs.length, addLog, isCollecting]);

  const startDataExtraction = useCallback(async () => {
    setIsExtractingData(true);
    clearLiveLog();
    addLiveLog("Initializing data extraction pipeline...");

    try {
      const ws = await connectWebSocket("extract");
      wsRef.current = ws;

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.status === "starting") {
          addLiveLog("Data extraction started...");
        } else if (data.status === "found_filings") {
          addLiveLog(`✓ Found ${data.count} XBRL filings in database`);
        } else if (data.status === "processing") {
          addLiveLog(`→ Processing ${data.scrip_code} (${data.report_type})`);
        } else if (data.status === "stored") {
          addLiveLog(`✓ ${data.scrip_code} data stored (${data.report_type})`);
          
          // Add individual company to Recent Runs
          const companyLog = {
            id: String(Date.now() + Math.random()),
            company: `${data.scrip_code}`,
            status: "success" as const,
            timestamp: new Date(),
            recordsProcessed: 1,
            message: `${data.report_type} data extracted`,
          };
          addLog(companyLog);
        } else if (data.status === "skipped_already_extracted") {
          addLiveLog(`⊘ ${data.scrip_code} already extracted, skipped`);
        } else if (data.status === "extracted") {
          addLiveLog(`✓ Data extracted and stored: ${data.scrip_code}`);
          
          // Add individual company to Recent Runs
          const companyLog = {
            id: String(Date.now() + Math.random()),
            company: `${data.scrip_code}`,
            status: "success" as const,
            timestamp: new Date(),
            recordsProcessed: 1,
            message: `Data extraction completed`,
          };
          addLog(companyLog);
          
          // Trigger callback to add company to master list
          if (onCompanyExtractedRef.current && data.company_data) {
            onCompanyExtractedRef.current(data.company_data);
          }
        } else if (data.status === "complete") {
          addLiveLog("✓ Data extraction complete!");
          setIsExtractingData(false);

          const newLog = {
            id: String(logs.length + 1),
            company: "All Companies (Data Extract)",
            status: "success",
            timestamp: new Date(),
            recordsProcessed: 1440,
            message: "Financial data extracted and stored",
          };
          addLog(newLog);
          ws.close();
          wsRef.current = null;
        } else if (data.error) {
          addLiveLog(`✗ Error: ${data.error}`);
        }
      };

      ws.onerror = () => {
        setIsExtractingData(false);
        addLiveLog("✗ WebSocket connection error");
      };

      ws.onclose = () => {
        if (isExtractingData) {
          addLiveLog("⟳ Connection closed (extraction may still be running on server)");
        }
      };
    } catch (error) {
      setIsExtractingData(false);
      const errorMsg = error instanceof Error ? error.message : String(error);
      addLiveLog(`✗ Failed to connect: ${errorMsg}`);
    }
  }, [connectWebSocket, addLiveLog, clearLiveLog, logs.length, addLog, isExtractingData]);

  const stopExtraction = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
      addLiveLog("✓ Extraction stopped by user");
      setIsCollecting(false);
      setIsExtractingData(false);
    }
  }, [addLiveLog]);

  return (
    <ExtractionContext.Provider
      value={{
        isCollecting,
        isExtractingData,
        liveLog,
        logs,
        startXbrlExtraction,
        startDataExtraction,
        stopExtraction,
        addLiveLog,
        addLog,
        clearLiveLog,
        clearLogs,
        wsRef,
        setOnCompanyExtracted,
      }}
    >
      {children}
    </ExtractionContext.Provider>
  );
};

export const useExtraction = () => {
  const context = useContext(ExtractionContext);
  if (!context) {
    throw new Error("useExtraction must be used within ExtractionProvider");
  }
  return context;
};
