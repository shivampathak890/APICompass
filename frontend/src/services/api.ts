import { HealthResponse } from "../types/health";
import { AnalyzePythonResponse } from "../types/ast";
import { DocRetrievalRequest, DocRetrievalResponse } from "../types/docs";
import { SseStreamParser } from "./sseParser";

export { SseStreamParser };

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL !== undefined && import.meta.env.VITE_API_BASE_URL !== null
  ? import.meta.env.VITE_API_BASE_URL
  : "";

export class ApiError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public errorCode?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}


/**
 * Fetch backend health status with timeout and resilient error handling.
 */
export async function fetchHealth(timeoutMs: number = 12000): Promise<HealthResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/health`, {
      method: "GET",
      headers: {
        "Accept": "application/json",
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new ApiError(`Health check returned status ${response.status}`, response.status);
    }

    const data = (await response.json()) as HealthResponse;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Health check request timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof Error) {
      throw new ApiError(`Unable to connect to backend: ${err.message}`);
    }
    throw new ApiError("An unknown network error occurred while connecting to backend.");
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Invoke static Python AST analysis endpoint.
 * Submitted source code is analyzed statically and NEVER executed.
 */
export async function analyzePythonCode(
  source: string,
  filename: string = "snippet.py",
  timeoutMs: number = 8000
): Promise<AnalyzePythonResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/analyze/python`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      body: JSON.stringify({ source, filename }),
      signal: controller.signal,
    });

    if (!response.ok) {
      if (response.status === 422) {
        throw new ApiError("Input rejected: source code exceeds maximum permitted size (100 KB).", 422);
      }
      throw new ApiError(`Analysis request failed with status ${response.status}`, response.status);
    }

    const data = (await response.json()) as AnalyzePythonResponse;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Analysis request timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof Error) {
      throw new ApiError(`Unable to connect to analysis service: ${err.message}`);
    }
    throw new ApiError("An unknown error occurred during static code analysis.");
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Identify API calls and map them to structured representations with confidence and ambiguity tracking.
 */
export async function identifyApiCalls(
  source: string,
  filename: string = "snippet.py",
  ecosystem: string = "stripe",
  timeoutMs: number = 8000
): Promise<import("../types/identification").IdentifyApiCallsResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/identify/python`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      body: JSON.stringify({ source, filename, ecosystem }),
      signal: controller.signal,
    });

    if (!response.ok) {
      if (response.status === 422) {
        throw new ApiError("Input rejected: source code exceeds maximum permitted size (100 KB) or payload is invalid.", 422);
      }
      throw new ApiError(`API call identification failed with status ${response.status}`, response.status);
    }

    const data = (await response.json()) as import("../types/identification").IdentifyApiCallsResponse;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`API call identification timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof Error) {
      throw new ApiError(`Unable to connect to identification service: ${err.message}`);
    }
    throw new ApiError("An unknown error occurred during API call identification.");
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Retrieve official documentation evidence for API candidates or queries.
 */
export async function retrieveDocumentation(
  request: DocRetrievalRequest,
  timeoutMs: number = 10000
): Promise<DocRetrievalResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/docs/retrieve`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new ApiError(`Documentation retrieval failed with status ${response.status}`, response.status);
    }

    const data = (await response.json()) as DocRetrievalResponse;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Documentation retrieval timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof Error) {
      throw new ApiError(`Unable to connect to documentation service: ${err.message}`);
    }
    throw new ApiError("An unknown error occurred during documentation retrieval.");
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Search candidate documentation pages relevant to an API query via TinyFish Search.
 */
export async function searchDocumentation(
  request: import("../types/docs").DocSearchRequest,
  timeoutMs: number = 10000
): Promise<import("../types/docs").DocSearchResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/docs/search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new ApiError(`Documentation search failed with status ${response.status}`, response.status);
    }

    const data = (await response.json()) as import("../types/docs").DocSearchResponse;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Documentation search timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof Error) {
      throw new ApiError(`Unable to connect to documentation search service: ${err.message}`);
    }
    throw new ApiError("An unknown error occurred during documentation search.");
  } finally {
    clearTimeout(timeoutId);
  }
}


/**
 * Execute unified evidence-based adjudication pipeline.
 * Coordinates AST analysis, documentation retrieval, deterministic quote verification,
 * and conservative verdict generation.
 */
export async function runUnifiedAnalysis(
  request: import("../types/evidence").AnalysisRequest,
  timeoutMs: number = 15000
): Promise<import("../types/evidence").AnalysisReport> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    if (!response.ok) {
      if (response.status === 422) {
        throw new ApiError("Input rejected: source code exceeds maximum permitted size (100 KB).", 422);
      }
      throw new ApiError(`Adjudication request failed with status ${response.status}`, response.status);
    }

    const data = (await response.json()) as import("../types/evidence").AnalysisReport;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Adjudication request timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof Error) {
      throw new ApiError(`Unable to connect to adjudication service: ${err.message}`);
    }
    throw new ApiError("An unknown error occurred during evidence adjudication.");
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Propose an evidence-gated fix for a candidate and perform safe static re-verification.
 */
export async function proposeFix(
  request: import("../types/fix_proposal").ProposeFixRequest,
  timeoutMs: number = 20000
): Promise<import("../types/fix_proposal").FixProposalResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/fixes/propose`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    if (!response.ok) {
      if (response.status === 422) {
        throw new ApiError("Input rejected: request payload contains invalid fields or exceeds maximum size.", 422);
      }
      throw new ApiError(`Fix proposal request failed with status ${response.status}`, response.status);
    }

    const data = (await response.json()) as import("../types/fix_proposal").FixProposalResponse;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Fix proposal request timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof Error) {
      throw new ApiError(`Unable to connect to fix proposal service: ${err.message}`);
    }
    throw new ApiError("An unknown error occurred during fix proposal generation.");
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Execute multi-file Python project static analysis and Evidence Court verification.
 */
export async function analyzeProject(
  request: import("../types/project").ProjectAnalysisRequest,
  timeoutMs: number = 25000
): Promise<import("../types/project").ProjectAnalysisReport> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/analyze/project`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    if (!response.ok) {
      if (response.status === 422) {
        const errorData = await response.json().catch(() => null);
        const detail = errorData?.detail?.[0]?.msg || errorData?.detail || "Invalid project submission.";
        throw new ApiError(`Project analysis rejected: ${detail}`, 422);
      }
      throw new ApiError(`Project analysis request failed with status ${response.status}`, response.status);
    }

    const data = (await response.json()) as import("../types/project").ProjectAnalysisReport;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Project analysis timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof Error) {
      throw new ApiError(`Unable to connect to project analysis service: ${err.message}`);
    }
    throw new ApiError("An unknown error occurred during project analysis.");
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * List paginated historical scan summaries.
 */
export async function listScans(
  limit: number = 20,
  offset: number = 0,
  verdict?: string,
  ecosystem?: string,
  timeoutMs: number = 8000
): Promise<import("../types/scan_history").ScanListResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    if (verdict) params.append("verdict", verdict);
    if (ecosystem) params.append("ecosystem", ecosystem);

    const response = await fetch(`${API_BASE_URL}/api/v1/scans?${params.toString()}`, {
      method: "GET",
      headers: {
        "Accept": "application/json",
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new ApiError(`Failed to fetch scan history: HTTP ${response.status}`, response.status);
    }

    const data = (await response.json()) as import("../types/scan_history").ScanListResponse;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`History list request timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) throw err;
    if (err instanceof Error) throw new ApiError(`Unable to fetch scan history: ${err.message}`);
    throw new ApiError("An unknown error occurred while retrieving scan history.");
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Retrieve full historical snapshot of a stored scan.
 * Does NOT call external services or rerun verification.
 */
export async function getScan(
  scanId: string,
  timeoutMs: number = 8000
): Promise<import("../types/scan_history").HistoricalScanDetail> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/scans/${encodeURIComponent(scanId)}`, {
      method: "GET",
      headers: {
        "Accept": "application/json",
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new ApiError(`Historical scan '${scanId}' was not found.`, 404);
      }
      throw new ApiError(`Failed to fetch scan detail: HTTP ${response.status}`, response.status);
    }

    const data = (await response.json()) as import("../types/scan_history").HistoricalScanDetail;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Scan detail request timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) throw err;
    if (err instanceof Error) throw new ApiError(`Unable to fetch scan detail: ${err.message}`);
    throw new ApiError("An unknown error occurred while retrieving scan detail.");
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Explicitly delete a historical scan record and its dependent records.
 */
export async function deleteScan(
  scanId: string,
  timeoutMs: number = 8000
): Promise<import("../types/scan_history").DeleteScanResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/scans/${encodeURIComponent(scanId)}`, {
      method: "DELETE",
      headers: {
        "Accept": "application/json",
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new ApiError(`Cannot delete scan '${scanId}': not found.`, 404);
      }
      throw new ApiError(`Failed to delete scan: HTTP ${response.status}`, response.status);
    }

    const data = (await response.json()) as import("../types/scan_history").DeleteScanResponse;
    return data;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Scan deletion request timed out after ${timeoutMs}ms`);
    }
    if (err instanceof ApiError) throw err;
    if (err instanceof Error) throw new ApiError(`Unable to delete scan: ${err.message}`);
    throw new ApiError("An unknown error occurred while deleting scan record.");
  } finally {
    clearTimeout(timeoutId);
  }
}

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

/**
 * Stream unified evidence-based analysis over Server-Sent Events (SSE).
 * Emits real-time progress events and final report via callback.
 * Implements WHATWG SSE specification for CRLF normalization, multi-line data fields,
 * buffer flushing on stream termination, and safe reader lock release.
 */
export async function streamUnifiedAnalysis(
  request: import("../types/evidence").AnalysisRequest,
  onEvent: (event: import("../types/stream").ScanProgressEvent) => void,
  signal?: AbortSignal
): Promise<import("../types/evidence").AnalysisReport> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/analyze/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
      },
      body: JSON.stringify(request),
      signal,
    });
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError("Analysis was cancelled by the user.", 499);
    }
    if (err instanceof Error) {
      throw new ApiError(
        `Cannot connect to APICompass backend at ${API_BASE_URL || "/api"}. The server may be offline or unreachable.`,
        0
      );
    }
    throw new ApiError("Failed to establish connection to the analysis backend.", 0);
  }

  if (!response.ok) {
    if (response.status === 422) {
      throw new ApiError("Input rejected: source code exceeds maximum permitted size (100 KB).", 422);
    }
    throw new ApiError(`Streaming analysis request failed with status ${response.status}`, response.status);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new ApiError("Streaming response body is unavailable.", 500);
  }

  let finalReport: import("../types/evidence").AnalysisReport | null = null;

  const parser = new SseStreamParser((parsedEvent) => {
    try {
      const ev = JSON.parse(parsedEvent.data) as import("../types/stream").ScanProgressEvent;
      onEvent(ev);
      if (ev.stage === "completed" && ev.report) {
        finalReport = ev.report;
      }
      if (ev.stage === "failed") {
        throw new ApiError(ev.message || "Analysis failed during streaming.", 500);
      }
    } catch (e) {
      if (e instanceof ApiError) throw e;
      // Malformed JSON is safely caught without crashing the active stream
      console.warn("Discarding malformed SSE event data:", parsedEvent.data);
    }
  });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        parser.finish();
        break;
      }
      if (value) {
        parser.feedBytes(value);
      }
    }
  } catch (readErr: unknown) {
    if (readErr instanceof Error && readErr.name === "AbortError") {
      throw new ApiError("Analysis was cancelled by the user.", 499);
    }
    if (readErr instanceof ApiError) {
      throw readErr;
    }
    throw new ApiError(
      `Streaming connection was interrupted before adjudication completed: ${readErr instanceof Error ? readErr.message : "Connection closed prematurely."}`,
      503
    );
  } finally {
    reader.releaseLock();
  }

  if (!finalReport) {
    throw new ApiError("Streaming connection ended without receiving final adjudication report.", 500);
  }

  return finalReport;
}


