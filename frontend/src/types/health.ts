export type ProviderLifecycleState = "disabled" | "missing_credentials" | "configured" | "unavailable";

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  timestamp: string;
  mock_mode: boolean;
  database_status?: string | null;
  provider_status?: Record<string, ProviderLifecycleState> | null;
}

export type ConnectionStatus = "connecting" | "connected" | "unavailable";

export interface SystemStatusState {
  status: ConnectionStatus;
  data: HealthResponse | null;
  error: string | null;
  lastChecked: Date | null;
}
