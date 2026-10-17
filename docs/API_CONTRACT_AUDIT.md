# APICompass v3 — Comprehensive FastAPI & Frontend API Contract Audit

This document establishes the official API contract between the APICompass FastAPI backend and the React TypeScript frontend, documenting request/response schemas, validation rules, standardized error envelopes, and contract synchronization policies.

---

## 1. Executive Summary

APICompass relies on a strictly typed, bi-directional contract between:
- **FastAPI Backend**: Pydantic v2 schemas (`backend/app/schemas/`) with strict validation, length constraints, regex filters, and zero secret leakage.
- **React Frontend**: TypeScript types (`frontend/src/types/`) and typed API services (`frontend/src/services/api.ts`).

### Key Guarantees
1. **Zero Stack Trace & Secret Leaks**: All `400`, `422`, and `500` responses return a sanitized `ErrorResponse` envelope. All error messages are filtered through `scrub_secrets()`, ensuring raw tokens or Stripe keys (e.g., `sk_live_...`) are redacted to `[REDACTED_STRIPE_LIVE_KEY]`.
2. **Payload Size & Shape Bounding**: Python source code is capped at 100 KB, file paths are bounded to 255 chars, and ecosystem identifiers must match `^[a-zA-Z0-9_\-]+$` (1–50 chars).
3. **Quarantine & Verification Integrity**: Result models prevent synthetic mock text from masquerading as verified official documentation (`unable_to_verify` with `MOCK FIXTURE QUARANTINE` when in mock mode).
4. **Resilient SSE Streaming**: Server-Sent Events use explicit, versioned event schemas (`ScanProgressEvent`) with graceful fallback to non-streaming REST analysis.

---

## 2. Standardized Error Response Envelope

All error responses across HTTP 400, 422, and 500 status codes strictly adhere to the `ErrorResponse` schema:

### Backend Schema (`backend/app/schemas/errors.py`)
```python
class ErrorDetailItem(BaseModel):
    loc: Optional[List[Union[str, int]]] = Field(None, description="Path to invalid field")
    msg: str = Field(..., description="Sanitized, human-readable error description")
    type: Optional[str] = Field(None, description="Pydantic validation error code")

class ErrorResponse(BaseModel):
    detail: str = Field(..., description="High-level sanitized summary of the error")
    error_code: str = Field("INTERNAL_ERROR", description="Machine-readable error classification")
    status_code: int = Field(500, description="HTTP status code")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    errors: Optional[List[ErrorDetailItem]] = Field(None, description="Field-level validation issues")
```

### Frontend TypeScript Interface (`frontend/src/types/errors.ts`)
```typescript
export interface ErrorDetailItem {
  loc?: (string | number)[] | null;
  msg: string;
  type?: string | null;
}

export interface ErrorResponse {
  detail: string;
  error_code: string;
  status_code: number;
  timestamp: string;
  errors?: ErrorDetailItem[] | null;
}
```

---

## 3. Complete Endpoint Contract Registry

| Method | Path | Request Schema | Response Schema | Status Codes | Description |
|---|---|---|---|---|---|
| `GET` | `/health` | None | `HealthResponse` | 200, 500 | System status, mock mode indicator, version |
| `POST` | `/api/v1/analyze/python` | `AnalysisRequest` | `AnalysisResult` | 200, 400, 422, 500 | AST parsing and call identification |
| `POST` | `/api/v1/analyze/identify` | `IdentifyApiCallsRequest` | `IdentifyApiCallsResponse` | 200, 422, 500 | Identifies supported vs unsupported SDK calls |
| `POST` | `/api/v1/analyze/unified` | `AnalysisRequest` | `AnalysisReport` | 200, 400, 422, 500 | Non-streaming AST + docs + contract court analysis |
| `POST` | `/api/v1/analyze/stream` | `AnalysisRequest` | `text/event-stream` (`ScanProgressEvent` / `AnalysisReport`) | 200, 400, 422, 500 | Real-time SSE streaming analysis with stage updates |
| `POST` | `/api/v1/analyze/project` | `ProjectAnalysisRequest` | `ProjectAnalysisReport` | 200, 400, 422, 500 | Multi-file directory scan (max 50 files, 5 MB total) |
| `POST` | `/api/v1/docs/retrieve` | `DocRetrievalRequest` | `DocRetrievalResponse` | 200, 400, 422, 500 | Official doc resolver with SSRF protection & mock quarantine |
| `POST` | `/api/v1/docs/search` | `DocSearchRequest` | `DocSearchResponse` | 200, 400, 422, 500 | Doc search with pagination and snippet extraction |
| `POST` | `/api/v1/fixes/propose` | `ProposeFixRequest` | `FixProposalResponse` | 200, 400, 422, 500 | Conservative fix proposal with AST re-validation |
| `GET` | `/api/v1/scans` | Query: `limit`, `offset` | `ScanHistoryResponse` | 200, 422, 500 | Historical scan audit trail |
| `GET` | `/api/v1/scans/{scan_id}` | Path: `scan_id` (`^scan_[a-f0-9]{16}$`) | `HistoricalScanDetail` | 200, 400, 404, 500 | Detailed audit record for an individual scan |

---

## 4. Request Model Validation Matrix

| Model | Field | Type | Constraints | Description |
|---|---|---|---|---|
| `AnalysisRequest` | `source` | `str` | `min_length=1, max_length=100,000` | Raw Python code to inspect |
| | `filename` | `str` | `min_length=1, max_length=255` | Source file label (default: `payment_handler.py`) |
| | `ecosystem` | `str` | `min_length=1, max_length=50, pattern=^[a-zA-Z0-9_\-]+$` | Target SDK ecosystem (`stripe`) |
| | `force_mock` | `bool` | Optional boolean | Force deterministic fixture mode |
| `IdentifyApiCallsRequest` | `source` | `str` | `min_length=1, max_length=100,000` | Python source code |
| | `ecosystem` | `str` | `min_length=1, max_length=50, pattern=^[a-zA-Z0-9_\-]+$` | Target ecosystem |
| `ProposeFixRequest` | `source` | `str` | `min_length=1, max_length=100,000` | Current Python source code |
| | `candidate_id` | `str` | `min_length=1, max_length=100` | Target finding candidate ID |
| | `ecosystem` | `str` | `min_length=1, max_length=50, pattern=^[a-zA-Z0-9_\-]+$` | Target ecosystem |
| `ProjectAnalysisRequest` | `files` | `List[ProjectFilePayload]` | `min_items=1, max_items=50` | List of project source files |
| `ProjectFilePayload` | `path` | `str` | `pattern=^[a-zA-Z0-9_\-./]+$`, no `..` | Relative safe path |
| | `source` | `str` | `max_length=100,000` | File content |
| `DocSearchRequest` | `query` | `str` | `min_length=1, max_length=200` | Search keywords |
| | `limit` | `int` | `ge=1, le=20` | Max search results |

---

## 5. Streaming Protocol & Event Schema

Streaming is powered by Server-Sent Events (`text/event-stream`) over HTTP POST `/api/v1/analyze/stream`:

### Event Types
- `event: progress` — Dispatched at each pipeline stage (`accepted`, `static_analysis_started`, `doc_search_started`, `doc_fetch_started`, `evidence_verification_started`, `ai_reasoning_started`, `persistence_started`).
- `event: error` — Dispatched if a processing step fails mid-stream.
- `event: complete` — Terminal payload containing the full `AnalysisReport`.

### Stage Enum Consistency
```python
ScanStageType = Literal[
    "accepted",
    "static_analysis_started",
    "static_analysis_completed",
    "doc_search_started",
    "doc_search_completed",
    "doc_fetch_started",
    "doc_fetch_completed",
    "documentation_retrieval_started",
    "documentation_retrieval_completed",
    "evidence_verification_started",
    "evidence_verification_completed",
    "ai_reasoning_started",
    "ai_reasoning_completed",
    "persistence_started",
    "persistence_completed",
    "completed",
    "failed",
]
```
Mirrored exactly in `frontend/src/types/stream.ts`.

---

## 6. How Client and Server Contracts Stay Synchronized

1. **Shared Schema Repository**: All core payload contracts originate from Pydantic schemas in `backend/app/schemas/`.
2. **TypeScript Mirror Types**: All TypeScript representations in `frontend/src/types/` match field-for-field, type-for-type, and optionality.
3. **Dual Verification Pipeline**:
   - Backend: Pytest suite (`backend/tests/test_api_endpoints_audit.py`, `test_state_handling.py`, etc.) asserting status codes, payload shapes, and error envelope uniformity.
   - Frontend: `tsc --noEmit` asserting zero type regressions, plus Playwright integration tests verifying live payload parsing, streaming stage transitions, and mock quarantine handling.
4. **Secret Scrubbing Filter**: The FastAPI application uses global exception handlers to redact any Stripe credentials or auth tokens prior to JSON serialization, preventing credentials from ever reaching the client interface.
