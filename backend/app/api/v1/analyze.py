"""API endpoints for static AST analysis and unified evidence-based adjudication."""

import logging
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from app.schemas.ast_analysis import AnalyzePythonRequest, AnalyzePythonResponse
from app.schemas.evidence import AnalysisRequest, AnalysisReport
from app.schemas.identification import IdentifyApiCallsRequest, IdentifyApiCallsResponse
from app.schemas.project_analysis import ProjectAnalysisRequest, ProjectAnalysisReport
from app.services.evidence.adjudicator import adjudicator
from app.services.evidence.stream_adjudicator import stream_adjudicator, format_sse
from app.services.identification import api_call_identifier
from app.services.project import project_adjudicator
from app.services.python_ast_analyzer import analyze_python_source
from app.repositories import get_scan_repository, ScanRepository

router = APIRouter(tags=["Analysis"])
logger = logging.getLogger("apicompass.analyze")


@router.post(
    "/analyze/python",
    response_model=AnalyzePythonResponse,
    status_code=status.HTTP_200_OK,
    summary="Static Python AST Analysis",
    description=(
        "Analyzes Python source code text using Python's built-in AST parser. "
        "Extracts imports, functions, classes, calls, heuristic candidates, and relevant literals. "
        "Submitted code is NEVER executed."
    ),
)
async def analyze_python(request: AnalyzePythonRequest) -> AnalyzePythonResponse:
    """Analyze Python source statically without execution."""
    logger.info(
        "Received static AST analysis request for file: %s (length: %d chars)",
        request.filename,
        len(request.source),
    )

    # Perform safe, zero-execution AST analysis
    result = analyze_python_source(source=request.source, filename=request.filename)

    logger.info(
        "Analysis complete for %s. Status: %s, Candidates: %d, Imports: %d",
        request.filename,
        result.status,
        len(result.candidates),
        len(result.imports),
    )
    return result


@router.post(
    "/identify/python",
    response_model=IdentifyApiCallsResponse,
    status_code=status.HTTP_200_OK,
    summary="Structured API Call Identification",
    description=(
        "Identifies and maps recognized Python code patterns to a structured representation "
        "including SDK/library, API resource, operation, symbol, arguments, location, "
        "and identification confidence, while strictly preserving ambiguity for unverified receivers."
    ),
)
async def identify_api_calls(request: IdentifyApiCallsRequest) -> IdentifyApiCallsResponse:
    """Identify API calls from Python source code text statically."""
    logger.info(
        "Received API call identification request for file: %s (length: %d chars)",
        request.filename,
        len(request.source),
    )
    result = api_call_identifier.identify_from_source(
        source=request.source,
        filename=request.filename,
        ecosystem=request.ecosystem,
    )
    logger.info(
        "Identification complete for %s. Confirmed: %d, Ambiguous: %d, Unsupported: %d",
        request.filename,
        result.confirmed_count,
        result.ambiguous_count,
        result.unsupported_count,
    )
    return result


@router.post(
    "/analyze",
    response_model=AnalysisReport,
    status_code=status.HTTP_200_OK,
    summary="Unified Evidence-Based Python API Verification",
    description=(
        "Orchestrates zero-execution AST analysis, official documentation retrieval, "
        "deterministic quote verification, API contract matching, and conservative adjudication. "
        "Distinguishes 'clean', 'issues_found', and 'unable_to_verify' outcomes."
    ),
)
async def analyze_unified(
    request: AnalysisRequest,
    repo: ScanRepository = Depends(get_scan_repository),
) -> AnalysisReport:
    """Run full evidence-based adjudication pipeline and persist audit record."""
    logger.info(
        "Received unified analysis request for file: %s (length: %d chars, ecosystem: %s)",
        request.filename,
        len(request.source),
        request.ecosystem,
    )
    report = await adjudicator.adjudicate(request)

    # Persist scan audit record to SQLite repository
    try:
        scan_id = repo.save_scan(request=request, report=report)
        report.scan_id = scan_id
        report.persistence_status = "saved"
    except Exception as e:
        logger.warning(
            "Failed to persist scan audit record for %s: %s",
            request.filename,
            type(e).__name__,
        )
        report.scan_id = None
        report.persistence_status = "failed"

    logger.info(
        "Adjudication completed for %s. Verdict: %s, Trust: %s, Issues: %d, Unresolved: %d, Scan ID: %s",
        request.filename,
        report.verdict,
        report.evidence_trust,
        len(report.verified_issues),
        len(report.unresolved_candidates),
        report.scan_id,
    )
    return report


@router.post(
    "/analyze/stream",
    status_code=status.HTTP_200_OK,
    summary="Real-time Streaming Evidence-Based Python API Verification",
    description=(
        "Streams truthful, real-time progress events over Server-Sent Events (SSE) during adjudication. "
        "Emits typed stages: accepted, static_analysis, ai_reasoning, doc_retrieval, "
        "evidence_verification, persistence, and terminal completed report."
    ),
)
async def analyze_unified_stream(
    request: AnalysisRequest,
    raw_request: Request,
    repo: ScanRepository = Depends(get_scan_repository),
) -> StreamingResponse:
    """Stream evidence verification events in real time via Server-Sent Events (SSE)."""
    logger.info(
        "Received streaming analysis request for file: %s (length: %d chars, ecosystem: %s)",
        request.filename,
        len(request.source),
        request.ecosystem,
    )

    async def event_generator():
        async for event in stream_adjudicator.stream_adjudicate(
            request=request,
            repo=repo,
            is_disconnected=raw_request.is_disconnected,
        ):
            yield format_sse(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/analyze/project",
    response_model=ProjectAnalysisReport,
    status_code=status.HTTP_200_OK,
    summary="Multi-File Python Project Analysis and Adjudication",
    description=(
        "Analyzes a bounded collection of Python files statically without code execution. "
        "Parses each file independently, resolves safe cross-file dependencies and imports, "
        "extracts API candidates, and verifies them against official documentation contracts."
    ),
)
async def analyze_project(
    request: ProjectAnalysisRequest,
    repo: ScanRepository = Depends(get_scan_repository),
) -> ProjectAnalysisReport:
    """Run static analysis and evidence adjudication across a multi-file Python project."""
    logger.info(
        "Received multi-file project analysis request for project '%s' (%d files, ecosystem: %s)",
        request.project_name,
        len(request.files),
        request.ecosystem,
    )
    report = await project_adjudicator.adjudicate_project(request=request, repo=repo)
    logger.info(
        "Project analysis completed for '%s'. Verdict: %s, Trust: %s, Issues: %d, Files: %d, Scan ID: %s",
        request.project_name,
        report.verdict,
        report.evidence_trust,
        len(report.verified_issues),
        len(report.files),
        report.scan_id,
    )
    return report
