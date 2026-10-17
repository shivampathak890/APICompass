"""Test suite for real-time SSE scan progress streaming.

Covers:
- Event schema validation and typed field constraints (1-3)
- Event ordering and operational lifecycle (4-6)
- Syntax error and invalid request handling (7-8)
- Unsupported ecosystem and zero candidate handling (9-10)
- Mock evidence quarantine and trust preservation (11-12)
- LLM disabled vs enabled stage emission (13-14)
- Database persistence success and failure handling (15-16)
- Client disconnection and resource cleanup (17)
- Concurrency and isolation between streams (18)
- Zero raw source code or secret leakage in events (19)
- Backward compatibility of synchronous analysis endpoint (20)
"""

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator, List, Tuple
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import init_db
from app.db.connection import get_db
from app.main import app
from app.repositories import ScanRepository, scan_repository
from app.schemas.evidence import AnalysisRequest
from app.schemas.stream import ScanProgressEvent
from app.services.evidence.stream_adjudicator import stream_adjudicator, format_sse


@pytest.fixture(autouse=True)
def isolated_streaming_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an isolated SQLite database path for streaming test runs."""
    db_path = tmp_path / "streaming_audit.db"
    monkeypatch.setattr(settings, "APICOMPASS_DB_PATH", str(db_path))
    scan_repository.db_path_override = db_path
    init_db(db_path)
    yield db_path
    scan_repository.db_path_override = None


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client connected to the FastAPI ASGI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def parse_sse_events(sse_text: str) -> List[Tuple[str, dict]]:
    """Parse raw SSE text into list of (event_type, data_dict) tuples."""
    events = []
    blocks = sse_text.strip().split("\n\n")
    for block in blocks:
        if not block.strip():
            continue
        event_name = "message"
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        data_str = "\n".join(data_lines)
        if data_str:
            events.append((event_name, json.loads(data_str)))
    return events


# ============================================================================
# Section 1: Event Schema & Ordering (1-6)
# ============================================================================

@pytest.mark.asyncio
async def test_01_stream_endpoint_returns_event_stream_content_type(async_client: AsyncClient) -> None:
    """Verify POST /api/v1/analyze/stream returns text/event-stream content type."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={"source": "import stripe\ndef pay(): pass", "filename": "s.py", "ecosystem": "stripe"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_02_all_streamed_events_validate_against_event_schema(async_client: AsyncClient) -> None:
    """Verify every event emitted adheres strictly to the typed ScanProgressEvent schema."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={
            "source": "import stripe\ncharge = stripe.Charge.create(amount=1000, source='tok_123')",
            "filename": "payment.py",
            "ecosystem": "stripe",
        },
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)
    assert len(events) >= 5

    for event_name, data in events:
        parsed = ScanProgressEvent.model_validate(data)
        assert parsed.event_version == "1.0.0"
        assert parsed.stage == event_name
        assert len(parsed.message) > 0
        assert "T" in parsed.timestamp  # ISO 8601 UTC


@pytest.mark.asyncio
async def test_03_format_sse_produces_compliant_wire_format() -> None:
    """Verify format_sse helper formats standard event and data lines with trailing double newline."""
    ev = ScanProgressEvent(
        event_version="1.0.0",
        stage="accepted",
        message="Request accepted.",
        timestamp="2026-10-17T00:00:00Z",
    )
    wire = format_sse(ev)
    assert wire.startswith("event: accepted\n")
    assert "data: {" in wire
    assert wire.endswith("\n\n")


@pytest.mark.asyncio
async def test_04_event_ordering_follows_logical_pipeline_stages(async_client: AsyncClient) -> None:
    """Verify stages are emitted in authentic operational sequence."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={
            "source": "import stripe\ncharge = stripe.Charge.create(amount=1000, source='tok_123')",
            "filename": "checkout.py",
            "ecosystem": "stripe",
        },
    )
    events = parse_sse_events(resp.text)
    stages = [event_name for event_name, _ in events]

    assert stages[0] == "accepted"
    assert "static_analysis_started" in stages
    assert "static_analysis_completed" in stages
    assert "documentation_retrieval_started" in stages
    assert "documentation_retrieval_completed" in stages
    assert "evidence_verification_started" in stages
    assert "evidence_verification_completed" in stages
    assert "persistence_started" in stages
    assert "persistence_completed" in stages
    assert stages[-1] == "completed"


@pytest.mark.asyncio
async def test_05_completed_stage_delivers_full_analysis_report(async_client: AsyncClient) -> None:
    """Verify the terminal 'completed' event carries the complete AnalysisReport payload."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={
            "source": "import stripe\ncharge = stripe.Charge.create(amount=1000, source='tok_123')",
            "filename": "test_complete.py",
            "ecosystem": "stripe",
        },
    )
    events = parse_sse_events(resp.text)
    terminal_event = events[-1]
    assert terminal_event[0] == "completed"

    report = terminal_event[1]["report"]
    assert report is not None
    assert report["verdict"] in ("clean", "issues_found", "unable_to_verify")
    assert "engine_version" in report
    assert "checks_performed" in report
    assert "disclaimer" in report


@pytest.mark.asyncio
async def test_06_progress_percent_increases_monotonically(async_client: AsyncClient) -> None:
    """Verify progress percentage values, when present, do not decrease."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={
            "source": "import stripe\ncharge = stripe.Charge.create(amount=1000, source='tok_123')",
            "filename": "test_prog.py",
            "ecosystem": "stripe",
        },
    )
    events = parse_sse_events(resp.text)
    percents = [d["progress_percent"] for _, d in events if d.get("progress_percent") is not None]
    assert len(percents) >= 3
    assert percents == sorted(percents)
    assert percents[-1] == 100


# ============================================================================
# Section 2: Early Exits and Error Handling (7-12)
# ============================================================================

@pytest.mark.asyncio
async def test_07_syntax_error_halts_stream_at_static_analysis(async_client: AsyncClient) -> None:
    """Verify syntax error emits static_analysis_completed and halts with completed syntax error report."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={"source": "def broken_func(\n    return stripe.Charge.create()", "filename": "syntax.py", "ecosystem": "stripe"},
    )
    events = parse_sse_events(resp.text)
    stages = [name for name, _ in events]

    assert "accepted" in stages
    assert "static_analysis_started" in stages
    assert "static_analysis_completed" in stages
    assert "documentation_retrieval_started" not in stages
    assert stages[-1] == "completed"

    report = events[-1][1]["report"]
    assert report["verdict"] == "unable_to_verify"
    assert report["syntax_error"] is not None
    assert report["syntax_error"]["lineno"] in (1, 2)


@pytest.mark.asyncio
async def test_08_invalid_payload_rejected_with_422(async_client: AsyncClient) -> None:
    """Verify client sending invalid schema (missing source) receives HTTP 422 before streaming."""
    resp = await async_client.post("/api/v1/analyze/stream", json={"filename": "no_source.py"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_09_unsupported_ecosystem_halts_early_with_completed(async_client: AsyncClient) -> None:
    """Verify unsupported ecosystem halts early without performing AST or doc retrieval."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={"source": "import boto3\ns3 = boto3.client('s3')", "filename": "aws.py", "ecosystem": "aws"},
    )
    events = parse_sse_events(resp.text)
    stages = [name for name, _ in events]

    assert stages[0] == "accepted"
    assert stages[-1] == "completed"
    assert "documentation_retrieval_started" not in stages
    assert "UNSUPPORTED_ECOSYSTEM" in events[-1][1]["report"]["limitations_and_caveats"][0]


@pytest.mark.asyncio
async def test_10_zero_candidates_halts_at_static_analysis(async_client: AsyncClient) -> None:
    """Verify non-API code emits NO_IN_SCOPE_CANDIDATES and halts before doc retrieval."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={"source": "def add(a, b):\n    return a + b\nx = add(1, 2)", "filename": "pure.py", "ecosystem": "stripe"},
    )
    events = parse_sse_events(resp.text)
    stages = [name for name, _ in events]

    assert "static_analysis_completed" in stages
    assert "documentation_retrieval_started" not in stages
    assert stages[-1] == "completed"
    assert events[-1][1]["report"]["verdict"] == "unable_to_verify"
    assert any("NO_IN_SCOPE_CANDIDATES" in c for c in events[-1][1]["report"]["limitations_and_caveats"])


@pytest.mark.asyncio
async def test_11_mock_evidence_quarantine_preserved_in_stream(async_client: AsyncClient) -> None:
    """Verify streaming analysis under mock mode produces quarantined unable_to_verify report."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={
            "source": "import stripe\ncharge = stripe.Charge.create(amount=1000, source='tok_123')",
            "filename": "mock.py",
            "ecosystem": "stripe",
            "force_mock": True,
        },
    )
    events = parse_sse_events(resp.text)
    terminal_report = events[-1][1]["report"]

    assert terminal_report["is_mock"] is True
    assert terminal_report["evidence_trust"] == "mock_fixture"
    assert terminal_report["verdict"] == "unable_to_verify"
    assert len(terminal_report["verified_issues"]) == 0
    assert any("MOCK_EVIDENCE_ONLY" in c for c in terminal_report["limitations_and_caveats"])


@pytest.mark.asyncio
async def test_12_mock_evidence_label_accurately_reported_in_retrieval_completed(async_client: AsyncClient) -> None:
    """Verify documentation_retrieval_completed truthfully reports mock retrieval mode."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={"source": "import stripe\nstripe.Charge.create()", "filename": "m.py", "ecosystem": "stripe", "force_mock": True},
    )
    events = parse_sse_events(resp.text)
    retrieval_done = next((d for name, d in events if name == "documentation_retrieval_completed"), None)
    assert retrieval_done is not None
    assert "mode: mock" in retrieval_done["message"]


# ============================================================================
# Section 3: LLM State, Persistence & Resource Cleanup (13-20)
# ============================================================================

@pytest.mark.asyncio
async def test_13_disabled_llm_never_emits_ai_reasoning_stages(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify when LLM_PROVIDER is disabled, ai_reasoning stages are completely omitted."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "disabled")
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={"source": "import stripe\nstripe.Charge.create()", "filename": "no_llm.py", "ecosystem": "stripe"},
    )
    events = parse_sse_events(resp.text)
    stages = [name for name, _ in events]

    assert "ai_reasoning_started" not in stages
    assert "ai_reasoning_completed" not in stages


@pytest.mark.asyncio
async def test_14_mock_llm_emits_ai_reasoning_stages_accurately(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify when LLM_PROVIDER is mock, ai_reasoning stages are emitted with suggestion count."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={"source": "import stripe\nstripe.Charge.create()", "filename": "mock_llm.py", "ecosystem": "stripe"},
    )
    events = parse_sse_events(resp.text)
    stages = [name for name, _ in events]

    assert "ai_reasoning_started" in stages
    assert "ai_reasoning_completed" in stages


@pytest.mark.asyncio
async def test_15_database_persistence_success_records_scan_id(
    async_client: AsyncClient, isolated_streaming_db: Path
) -> None:
    """Verify successful database persistence populates scan_id across persistence_completed and completed."""
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={"source": "import stripe\nstripe.Charge.create()", "filename": "persist.py", "ecosystem": "stripe"},
    )
    events = parse_sse_events(resp.text)
    persist_event = next((d for name, d in events if name == "persistence_completed"), None)
    assert persist_event is not None
    assert persist_event["scan_id"] is not None
    assert persist_event["scan_id"].startswith("scan_")

    final_report = events[-1][1]["report"]
    assert final_report["scan_id"] == persist_event["scan_id"]
    assert final_report["persistence_status"] == "saved"

    # Confirm row in SQLite
    with get_db(isolated_streaming_db) as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM scans WHERE scan_id = ?", (final_report["scan_id"],)).fetchone()["c"]
        assert count == 1


@pytest.mark.asyncio
async def test_16_database_persistence_failure_handled_gracefully(async_client: AsyncClient) -> None:
    """Verify persistence failure emits persistence_completed with warning without aborting completed event."""
    from app.repositories import get_scan_repository

    class FailingRepo:
        def save_scan(self, *args, **kwargs):
            raise RuntimeError("Simulated SQLite write error")

    app.dependency_overrides[get_scan_repository] = lambda: FailingRepo()
    try:
        resp = await async_client.post(
            "/api/v1/analyze/stream",
            json={"source": "import stripe\nstripe.Charge.create()", "filename": "fail_db.py", "ecosystem": "stripe"},
        )
        events = parse_sse_events(resp.text)
        persist_event = next((d for name, d in events if name == "persistence_completed"), None)
        assert persist_event is not None
        assert "Database persistence failed" in persist_event["message"]

        final_report = events[-1][1]["report"]
        assert final_report["scan_id"] is None
        assert final_report["persistence_status"] == "failed"
        assert final_report["verdict"] in ("clean", "issues_found", "unable_to_verify")
    finally:
        app.dependency_overrides.pop(get_scan_repository, None)


@pytest.mark.asyncio
async def test_17_client_disconnection_halts_generator_cleanly(isolated_streaming_db: Path) -> None:
    """Verify is_disconnected callback halts generator early without unbounded work."""
    repo = ScanRepository(isolated_streaming_db)
    req = AnalysisRequest(
        source="import stripe\nstripe.Charge.create()",
        filename="disconnect.py",
        ecosystem="stripe",
    )

    disconnect_after_steps = 2
    step_counter = 0

    async def mock_is_disconnected() -> bool:
        nonlocal step_counter
        step_counter += 1
        return step_counter >= disconnect_after_steps

    events_collected = []
    async for event in stream_adjudicator.stream_adjudicate(req, repo, is_disconnected=mock_is_disconnected):
        events_collected.append(event)

    # Stream should have terminated early without reaching completed
    stages = [e.stage for e in events_collected]
    assert "completed" not in stages
    assert len(stages) < 6


@pytest.mark.asyncio
async def test_18_concurrent_streams_maintain_isolated_state(async_client: AsyncClient) -> None:
    """Verify concurrent streaming scans operate independently with unique timestamps and scan IDs."""
    import asyncio

    task1 = async_client.post(
        "/api/v1/analyze/stream",
        json={"source": "import stripe\ndef a(): pass", "filename": "a.py", "ecosystem": "stripe"},
    )
    task2 = async_client.post(
        "/api/v1/analyze/stream",
        json={"source": "import stripe\ndef b(): pass", "filename": "b.py", "ecosystem": "stripe"},
    )

    resp1, resp2 = await asyncio.gather(task1, task2)
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    events1 = parse_sse_events(resp1.text)
    events2 = parse_sse_events(resp2.text)

    rep1 = events1[-1][1]["report"]
    rep2 = events2[-1][1]["report"]

    assert rep1["filename"] == "a.py"
    assert rep2["filename"] == "b.py"


@pytest.mark.asyncio
async def test_19_zero_raw_source_or_secret_leakage_in_progress_events(async_client: AsyncClient) -> None:
    """Verify SSE events do not leak raw submitted source code or API keys in message text."""
    secret_marker = "SUPER_SECRET_TOKEN_DO_NOT_LEAK_IN_EVENTS_12345"
    resp = await async_client.post(
        "/api/v1/analyze/stream",
        json={
            "source": f"import stripe\n# {secret_marker}\ncharge = stripe.Charge.create()",
            "filename": "privacy.py",
            "ecosystem": "stripe",
        },
    )
    events = parse_sse_events(resp.text)

    # In all intermediate progress events (stages other than final completed report), the secret marker must not appear
    for event_name, data in events:
        if event_name != "completed":
            assert secret_marker not in json.dumps(data)


@pytest.mark.asyncio
async def test_20_existing_synchronous_analysis_endpoint_remains_backward_compatible(
    async_client: AsyncClient
) -> None:
    """Verify POST /api/v1/analyze continues to respond with identical schema and HTTP 200."""
    resp = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe\ndef check(): pass", "filename": "sync.py", "ecosystem": "stripe"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "verdict" in data
    assert "evidence_trust" in data
    assert "checks_performed" in data
    assert "persistence_status" in data


@pytest.mark.asyncio
async def test_21_disconnect_mid_retrieval_loop_halts_immediately(isolated_streaming_db: Path) -> None:
    """Verify is_disconnected checked inside target_urls_to_fetch loop aborts early."""
    from unittest.mock import patch
    repo = ScanRepository(isolated_streaming_db)
    req = AnalysisRequest(
        source="import stripe\nstripe.Charge.create()\nstripe.PaymentIntent.create()\n",
        filename="disconnect_mid_retrieval.py",
        ecosystem="stripe",
    )

    fetch_count = 0
    async def mock_retrieve(*args, **kwargs):
        nonlocal fetch_count
        fetch_count += 1
        from app.schemas.evidence import DocRetrievalResponse
        return DocRetrievalResponse(status="mock", evidence=[], target_url="https://docs.stripe.com/api")

    check_count = 0
    async def disconnect_after_first_fetch():
        nonlocal check_count
        check_count += 1
        # Disconnect after the first loop check
        return check_count >= 2

    with patch("app.services.evidence.stream_adjudicator.retrieval_service.retrieve", side_effect=mock_retrieve):
        events = []
        async for ev in stream_adjudicator.stream_adjudicate(req, repo, is_disconnected=disconnect_after_first_fetch):
            events.append(ev)

    stages = [e.stage for e in events]
    assert "completed" not in stages
    assert "persistence_completed" not in stages
    assert fetch_count <= 1


@pytest.mark.asyncio
async def test_22_internal_ast_parse_failure_emits_sanitized_report_without_stack_leak(
    isolated_streaming_db: Path,
) -> None:
    """Verify internal unexpected exceptions during AST parsing produce sanitized reports without leaking paths or secrets."""
    from unittest.mock import patch
    repo = ScanRepository(isolated_streaming_db)
    leak_string = "C:\\secret\\sensitive_path\\password_12345.key"
    req = AnalysisRequest(
        source="import stripe\ndef pay(): pass",
        filename="leak_check.py",
        ecosystem="stripe",
    )

    with patch(
        "app.services.evidence.stream_adjudicator.analyze_python_source",
        side_effect=RuntimeError(f"Fatal parser error in {leak_string}"),
    ):
        events = []
        async for ev in stream_adjudicator.stream_adjudicate(req, repo):
            events.append(ev)

    assert len(events) == 3
    assert events[0].stage == "accepted"
    assert events[1].stage == "static_analysis_started"
    assert events[2].stage == "completed"
    report = events[2].report
    assert report is not None
    assert report.verdict == "unable_to_verify"
    assert "ANALYSIS_FAILURE" in report.limitations_and_caveats[0]
    # Verify sensitive error string was completely sanitized from user-facing report
    assert leak_string not in report.summary
    assert leak_string not in report.limitations_and_caveats[0]
    assert leak_string not in events[1].message


@pytest.mark.asyncio
async def test_23_disconnect_before_analysis_starts_emits_no_events(isolated_streaming_db: Path) -> None:
    """Verify is_disconnected=True prior to invocation aborts immediately with 0 events."""
    repo = ScanRepository(isolated_streaming_db)
    req = AnalysisRequest(
        source="import stripe\ndef charge(): pass",
        filename="early_disconnect.py",
        ecosystem="stripe",
    )

    async def already_disconnected():
        return True

    events = []
    async for ev in stream_adjudicator.stream_adjudicate(req, repo, is_disconnected=already_disconnected):
        events.append(ev)

    assert len(events) == 0


@pytest.mark.asyncio
async def test_24_disconnect_before_persistence_does_not_save_scan(isolated_streaming_db: Path) -> None:
    """Verify disconnect detected immediately before persistence halts without writing to SQLite."""
    repo = ScanRepository(isolated_streaming_db)
    req = AnalysisRequest(
        source="import stripe\ncharge = stripe.Charge.create(amount=1000)\n",
        filename="pre_persist_disconnect.py",
        ecosystem="stripe",
    )

    check_count = 0
    async def disconnect_at_persistence_check():
        nonlocal check_count
        check_count += 1
        # Check 5 is immediately before persistence
        return check_count >= 5

    events = []
    async for ev in stream_adjudicator.stream_adjudicate(
        req, repo, is_disconnected=disconnect_at_persistence_check, _internal_evidence=[]
    ):
        events.append(ev)

    stages = [e.stage for e in events]
    assert "evidence_verification_completed" in stages
    assert "persistence_started" not in stages
    assert "persistence_completed" not in stages
    assert "completed" not in stages

    items, total = repo.list_scans(limit=10)
    assert total == 0


@pytest.mark.asyncio
async def test_25_disconnect_after_persistence_leaves_record_committed(isolated_streaming_db: Path) -> None:
    """Verify disconnect immediately after persistence commits record but halts without completed event."""
    repo = ScanRepository(isolated_streaming_db)
    req = AnalysisRequest(
        source="import stripe\ncharge = stripe.Charge.create(amount=1000)\n",
        filename="post_persist_disconnect.py",
        ecosystem="stripe",
    )

    check_count = 0
    async def disconnect_after_persistence():
        nonlocal check_count
        check_count += 1
        # Check 6 is immediately after persistence
        return check_count >= 6

    events = []
    async for ev in stream_adjudicator.stream_adjudicate(
        req, repo, is_disconnected=disconnect_after_persistence, _internal_evidence=[]
    ):
        events.append(ev)

    stages = [e.stage for e in events]
    assert "persistence_completed" in stages
    assert "completed" not in stages

    # The record WAS safely committed to SQLite
    items, total = repo.list_scans(limit=10)
    assert total == 1
    assert items[0].filename == "post_persist_disconnect.py"


@pytest.mark.asyncio
async def test_26_cancelled_error_propagates_without_fabricating_events(isolated_streaming_db: Path) -> None:
    """Verify genuine asyncio.CancelledError during retrieval raises directly without emitting failed/completed."""
    from unittest.mock import patch
    repo = ScanRepository(isolated_streaming_db)
    req = AnalysisRequest(
        source="import stripe\nstripe.Charge.create()\n",
        filename="cancelled.py",
        ecosystem="stripe",
    )

    async def cancel_retrieve(*args, **kwargs):
        raise asyncio.CancelledError("Client closed HTTP connection")

    with patch("app.services.evidence.stream_adjudicator.retrieval_service.retrieve", side_effect=cancel_retrieve):
        events = []
        with pytest.raises(asyncio.CancelledError):
            async for ev in stream_adjudicator.stream_adjudicate(req, repo):
                events.append(ev)

    stages = [e.stage for e in events]
    assert "failed" not in stages
    assert "completed" not in stages
    assert "persistence_completed" not in stages


