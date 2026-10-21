import React, { useState, useEffect, useCallback } from "react";
import { AppHeader } from "./components/AppHeader";
import { CodeEditorPlaceholder } from "./components/CodeEditorPlaceholder";
import { StatusCard } from "./components/StatusCard";
import { fetchHealth, getApiBaseUrl } from "./services/api";
import { HealthResponse, ConnectionStatus } from "./types/health";

export const App: React.FC = () => {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");
  const [healthData, setHealthData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const checkHealth = useCallback(async () => {
    setConnectionStatus("connecting");
    setError(null);
    try {
      const data = await fetchHealth();
      setHealthData(data);
      setConnectionStatus("connected");
      setLastChecked(new Date());
    } catch (err: unknown) {
      setConnectionStatus("unavailable");
      setLastChecked(new Date());
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unable to connect to API backend");
      }
    }
  }, []);

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  const mockMode = healthData?.mock_mode ?? true;
  const version = healthData?.version ?? "0.1.0";
  const apiBaseUrl = getApiBaseUrl();

  return (
    <div className="flex flex-col min-h-screen bg-[#F8FAFC] text-[#0F172A] font-sans selection:bg-[#163A6E] selection:text-white">
      <AppHeader mockMode={mockMode} version={version} />

      <main className="flex-1 flex flex-col">
        <CodeEditorPlaceholder backendStatus={connectionStatus} mockMode={mockMode} />
      </main>

      <StatusCard
        connectionStatus={connectionStatus}
        healthData={healthData}
        error={error}
        lastChecked={lastChecked}
        onRefresh={checkHealth}
        apiBaseUrl={apiBaseUrl}
      />
    </div>
  );
};

export default App;
