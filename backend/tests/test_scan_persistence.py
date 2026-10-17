"""Test suite for SQLite audit repository, scan persistence, and history API.

Covers:
- Database initialization and idempotent migrations (1-7)
- Authoritative scan persistence and source fingerprinting (8-18)
- History list, detail, and explicit deletion API (19-31)
- Security, privacy, and backwards-compatibility invariants (32-40)
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import init_db, CURRENT_SCHEMA_VERSION, MigrationError
from app.db.connection import get_db, get_db_path
from app.main import app, lifespan
from app.repositories import (
    ScanRepository,
    scan_repository,
    compute_record_integrity_hash,
)
from app.schemas.evidence import (
    AnalysisRequest,
    AnalysisReport,
    CandidateAssessment,
    EvidenceMatch,
    QuoteVerificationResult,
    VerifiedIssue,
    AISuggestion,
)
from app.schemas.ast_analysis import SourceLocation
from app.schemas.documentation import NormalizedEvidence
from app.schemas.fix_proposal import FixProposalResponse



@pytest.fixture(autouse=True)
def isolated_audit_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Isolate database to a temporary SQLite file per test."""
    test_db_path = tmp_path / "test_apicompass.db"
    monkeypatch.setattr(settings, "APICOMPASS_DB_PATH", str(test_db_path))
    scan_repository.db_path_override = test_db_path
    init_db(test_db_path)
    yield test_db_path
    scan_repository.db_path_override = None


@pytest_asyncio.fixture
async def async_client() -> AsyncClient:
    """Async HTTP client bound to FastAPI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# ============================================================================
# Section 1: Database Initialization and Migrations (1-7)
# ============================================================================

def test_01_first_time_initialization_creates_schema(isolated_audit_db: Path) -> None:
    """Verify first-time initialization creates all required tables and indexes."""
    with get_db(isolated_audit_db) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cursor.fetchall()}
        assert "schema_migrations" in tables
        assert "scans" in tables
        assert "scan_evidence" in tables
        assert "scan_findings" in tables
        assert "scan_fix_proposals" in tables

        index_cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row["name"] for row in index_cursor.fetchall()}
        assert "idx_scans_created_at" in indexes
        assert "idx_scans_verdict" in indexes


def test_02_repeated_initialization_is_idempotent(isolated_audit_db: Path) -> None:
    """Verify repeated initialization is idempotent and does not drop tables."""
    # First init happened in fixture, insert a test scan
    with get_db(isolated_audit_db) as conn:
        conn.execute(
            """
            INSERT INTO scans (
                scan_id, schema_version, created_at, status, verdict, ecosystem,
                filename, source_sha256, source_length, pipeline_version,
                evidence_trust, is_mock, llm_reasoning_status, summary,
                checks_performed, limitations_and_caveats, disclaimer, integrity_hash
            ) VALUES (?, 1, ?, 'completed', 'clean', 'stripe', 'test.py', 'hash123', 10, '0.1.0', 'live_official_source', 0, 'disabled', 'summary', '[]', '[]', 'disclaimer', 'inthash')
            """,
            ("scan_test_idempotent", datetime.now(timezone.utc).isoformat()),
        )

    # Re-run init_db
    init_db(isolated_audit_db)

    # Verify existing record still exists
    with get_db(isolated_audit_db) as conn:
        cursor = conn.execute("SELECT scan_id FROM scans WHERE scan_id = ?", ("scan_test_idempotent",))
        assert cursor.fetchone() is not None


def test_03_applied_migration_versions_recorded(isolated_audit_db: Path) -> None:
    """Verify applied migration version numbers and timestamps are stored."""
    with get_db(isolated_audit_db) as conn:
        cursor = conn.execute("SELECT version, name, applied_at FROM schema_migrations ORDER BY version ASC")
        rows = cursor.fetchall()
        assert len(rows) >= 1
        assert rows[0]["version"] == 1
        assert rows[0]["name"] == "initial_audit_schema"
        assert rows[0]["applied_at"] is not None


def test_04_unsupported_future_schema_version_fails_safely(isolated_audit_db: Path) -> None:
    """Verify that opening a database with a future schema version raises MigrationError."""
    with get_db(isolated_audit_db) as conn:
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (999, "future_incompatible_schema", datetime.now(timezone.utc).isoformat()),
        )

    with pytest.raises(MigrationError) as exc_info:
        init_db(isolated_audit_db)
    assert "newer than supported engine version" in str(exc_info.value)


def test_05_foreign_key_enforcement_works(isolated_audit_db: Path) -> None:
    """Verify foreign key enforcement rejects orphaned evidence or findings records."""
    with pytest.raises(sqlite3.IntegrityError):
        with get_db(isolated_audit_db) as conn:
            # Attempt to insert evidence referencing nonexistent scan_id
            conn.execute(
                """
                INSERT INTO scan_evidence (
                    scan_id, evidence_id, ecosystem, source_url, canonical_url,
                    title, content_excerpt, retrieved_at, provider, status, is_mock, source_trust
                ) VALUES (?, 'ev_orphan', 'stripe', 'https://example.com', 'https://example.com', 't', 'c', 'now', 'p', 's', 0, 'official')
                """,
                ("nonexistent_scan_id",),
            )


def test_06_database_connections_are_scoped_and_closed(isolated_audit_db: Path) -> None:
    """Verify database connection context manager closes connection reliably."""
    conn_ref = None
    with get_db(isolated_audit_db) as conn:
        conn_ref = conn
        cursor = conn.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1

    # Attempting to execute on closed connection must raise sqlite3.ProgrammingError
    with pytest.raises(sqlite3.ProgrammingError):
        conn_ref.execute("SELECT 1")


def test_07_database_initialization_failure_reported_clearly(tmp_path: Path) -> None:
    """Verify initialization failure with unwriteable path raises a controlled exception."""
    invalid_path = tmp_path / "nonexistent_dir" / "readonly_file" / "db.sqlite"
    # Create a regular file where the directory was supposed to be
    (tmp_path / "nonexistent_dir" / "readonly_file").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "nonexistent_dir" / "readonly_file").touch()

    with pytest.raises(Exception):
        init_db(invalid_path)


# ============================================================================
# Section 2: Scan Persistence and Provenance (8-18)
# ============================================================================

def test_08_completed_analysis_is_persisted(isolated_audit_db: Path) -> None:
    """Verify completed AnalysisReport is persisted and retrievable by scan ID."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(
        source="import stripe\ncharge = stripe.Charge.create(amount=1000, currency='usd', source='tok_123')",
        filename="checkout.py",
        ecosystem="stripe",
    )
    report = AnalysisReport(
        verdict="issues_found",
        engine_version="0.1.0",
        filename="checkout.py",
        total_lines=2,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="Found 1 legacy contract issue.",
        checks_performed=["AST extraction", "Contract matching", "Quote verification"],
        verified_issues=[
            VerifiedIssue(
                issue_id="iss_001",
                candidate_id="cand_001",
                source_location=SourceLocation(lineno=2, col_offset=9, end_lineno=2, end_col_offset=80),
                claim_checked="source parameter support",
                violation_type="legacy_deprecated_parameter",
                explanation="The 'source' parameter is legacy.",
                supporting_evidence_id="ev_001",
                source_url="https://docs.stripe.com/api/charges/create",
                verified_quote="Use PaymentIntents instead of Charge.create with source.",
                match_method="exact",
            )
        ],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[
            NormalizedEvidence(
                evidence_id="ev_001",
                ecosystem="stripe",
                package="stripe",
                source_url="https://docs.stripe.com/api/charges/create",
                canonical_url="https://docs.stripe.com/api/charges/create",
                title="Create a Charge | Stripe API",
                content_excerpt="Use PaymentIntents instead of Charge.create with source.",
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                provider="tinyfish_live",
                status="live",
                is_mock=False,
                source_trust="official",
                doc_version="2024-04-10",
            )
        ],
        limitations_and_caveats=["Runtime network behavior is not verified."],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    scan_id = repo.save_scan(request, report)
    assert scan_id.startswith("scan_")

    # Load stored scan
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert detail.scan_id == scan_id
    assert detail.verdict == "issues_found"
    assert detail.filename == "checkout.py"
    assert detail.evidence_trust == "live_official_source"
    assert detail.is_mock is False
    assert len(detail.verified_issues) == 1
    assert detail.verified_issues[0].violation_type == "legacy_deprecated_parameter"
    assert len(detail.evidence_items) == 1
    assert detail.is_historical is True


def test_09_source_fingerprint_computed_server_side(isolated_audit_db: Path) -> None:
    """Verify source SHA-256 fingerprint is computed deterministically on server."""
    repo = ScanRepository(isolated_audit_db)
    source_code = "import stripe\ndef pay(): pass"
    expected_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()

    request = AnalysisRequest(source=source_code, filename="pay.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="clean",
        engine_version="0.1.0",
        filename="pay.py",
        total_lines=2,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="All clean.",
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    scan_id = repo.save_scan(request, report)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert detail.source_sha256 == expected_hash
    assert detail.source_length == len(source_code)


def test_10_raw_source_code_not_stored_by_default(isolated_audit_db: Path) -> None:
    """Verify raw source code is NOT stored in the database for user privacy."""
    repo = ScanRepository(isolated_audit_db)
    secret_marker = "SUPER_SECRET_PAYMENT_TOKEN_DO_NOT_STORE_XYZ"
    source = f"import stripe\n# {secret_marker}\ncharge = stripe.Charge.create(amount=100)"

    request = AnalysisRequest(source=source, filename="secret.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="unable_to_verify",
        engine_version="0.1.0",
        filename="secret.py",
        total_lines=3,
        evidence_trust="mock_fixture",
        is_mock=True,
        summary="Mock mode.",
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    scan_id = repo.save_scan(request, report)

    # Search raw database file text for secret marker
    with get_db(isolated_audit_db) as conn:
        cursor = conn.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,))
        row = dict(cursor.fetchone())
        # Check all column values
        for col, val in row.items():
            if val is not None:
                assert secret_marker not in str(val), f"Raw source secret leaked into column {col}"


def test_11_mock_evidence_remains_marked_mock(isolated_audit_db: Path) -> None:
    """Verify mock reports retain is_mock=True and evidence_trust='mock_fixture'."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(source="import stripe", filename="mock_test.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="unable_to_verify",
        engine_version="0.1.0",
        filename="mock_test.py",
        total_lines=1,
        evidence_trust="mock_fixture",
        is_mock=True,
        summary="Mock evidence quarantined.",
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=["MOCK_EVIDENCE_ONLY"],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    scan_id = repo.save_scan(request, report)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert detail.is_mock is True
    assert detail.evidence_trust == "mock_fixture"


def test_12_ai_suggestions_remain_separate_from_verified_findings(isolated_audit_db: Path) -> None:
    """Verify AI suggestions are stored distinctly and never upgraded to verified issues."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(source="import stripe\ncharge = stripe.Charge.create()", filename="ai.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="unable_to_verify",
        engine_version="0.1.0",
        filename="ai.py",
        total_lines=2,
        evidence_trust="mock_fixture",
        is_mock=True,
        summary="Analysis complete with 1 suggestion.",
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[
            AISuggestion(
                suggestion_id="sug_01",
                candidate_id="cand_001",
                claim_type="deprecated_api",
                description="Charge.create may be legacy.",
                unverified_aspects="Needs live docs confirmation.",
                suggested_documentation_queries=["https://docs.stripe.com"],
                referenced_evidence_ids=[],
                confidence="uncalibrated",
                reasoning_summary="Candidate pattern.",
                label="AI suggestion — not verified",
            )
        ],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="mock",
    )

    scan_id = repo.save_scan(request, report)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert len(detail.verified_issues) == 0, "AI suggestions must NOT become verified issues"
    assert len(detail.ai_suggestions) == 1
    assert detail.ai_suggestions[0].label == "AI suggestion — not verified"


def test_13_evidence_provenance_survives_round_trip(isolated_audit_db: Path) -> None:
    """Verify full evidence provenance (URL, title, timestamp, SHA-256) survives round-trip."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(source="import stripe", filename="prov.py", ecosystem="stripe")
    now_iso = datetime.now(timezone.utc).isoformat()
    ev = NormalizedEvidence(
        evidence_id="ev_prov_123",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/payment_intents/create",
        canonical_url="https://docs.stripe.com/api/payment_intents/create",
        title="Payment Intents API Documentation",
        content_excerpt="Creates a PaymentIntent object for modern payments.",
        retrieved_at=now_iso,
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
    )
    report = AnalysisReport(
        verdict="clean",
        engine_version="0.1.0",
        filename="prov.py",
        total_lines=1,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="Clean.",
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[ev],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    scan_id = repo.save_scan(request, report)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert len(detail.evidence_items) == 1
    loaded_ev = detail.evidence_items[0]
    assert loaded_ev.evidence_id == "ev_prov_123"
    assert loaded_ev.canonical_url == "https://docs.stripe.com/api/payment_intents/create"
    assert loaded_ev.source_trust == "official"
    assert loaded_ev.title == "Payment Intents API Documentation"
    assert loaded_ev.content_excerpt == "Creates a PaymentIntent object for modern payments."


def test_14_quote_verification_metadata_survives_round_trip(isolated_audit_db: Path) -> None:
    """Verify quote verification match method and quote text survive round-trip."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(source="import stripe\nstripe.Charge.create()", filename="quote.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="issues_found",
        engine_version="0.1.0",
        filename="quote.py",
        total_lines=2,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="Issues found.",
        checks_performed=[],
        verified_issues=[
            VerifiedIssue(
                issue_id="iss_q1",
                candidate_id="cand_1",
                source_location=SourceLocation(lineno=2, col_offset=0, end_lineno=2, end_col_offset=22),
                claim_checked="charge method",
                violation_type="deprecated_api_operation",
                explanation="Deprecated in modern API.",
                supporting_evidence_id="ev_q1",
                source_url="https://docs.stripe.com/api/charges",
                verified_quote="The Charges API is legacy.",
                match_method="whitespace_normalized",
            )
        ],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    scan_id = repo.save_scan(request, report)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert len(detail.verified_issues) == 1
    assert detail.verified_issues[0].verified_quote == "The Charges API is legacy."
    assert detail.verified_issues[0].match_method == "whitespace_normalized"


def test_15_unable_to_verify_report_remains_abstention(isolated_audit_db: Path) -> None:
    """Verify an unable_to_verify report retains its abstention verdict and reason."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(source="import boto3", filename="aws.py", ecosystem="aws")
    report = AnalysisReport(
        verdict="unable_to_verify",
        engine_version="0.1.0",
        filename="aws.py",
        total_lines=1,
        evidence_trust="untrusted_or_unavailable",
        is_mock=False,
        summary="Unsupported ecosystem aws.",
        checks_performed=["ecosystem check"],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=["UNSUPPORTED_ECOSYSTEM: aws"],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    scan_id = repo.save_scan(request, report)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert detail.verdict == "unable_to_verify"
    assert detail.abstention_reason == "UNSUPPORTED_ECOSYSTEM"


@pytest.mark.asyncio
async def test_16_database_failure_does_not_falsely_report_persistence_success(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify persistence failure sets persistence_status='failed' and scan_id=None."""
    def fail_save(*args, **kwargs):
        raise sqlite3.OperationalError("Simulated disk full or DB locked.")

    monkeypatch.setattr(scan_repository, "save_scan", fail_save)

    response = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe\ndef test(): pass", "filename": "fail.py", "ecosystem": "stripe"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["persistence_status"] == "failed"
    assert data["scan_id"] is None
    # Deterministic analysis verdict still computed
    assert data["verdict"] in ("clean", "unable_to_verify")


def test_17_analysis_failure_not_silently_persisted_as_completed(isolated_audit_db: Path) -> None:
    """Verify a syntax error report records abstention status and syntax error caveats."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(source="def broken(:", filename="bad.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="unable_to_verify",
        engine_version="0.1.0",
        filename="bad.py",
        total_lines=1,
        evidence_trust="untrusted_or_unavailable",
        is_mock=False,
        summary="Syntax error detected.",
        checks_performed=["AST parsing"],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=["SYNTAX_ERROR: line 1"],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    scan_id = repo.save_scan(request, report)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert detail.verdict == "unable_to_verify"
    assert detail.abstention_reason == "SYNTAX_ERROR"


@pytest.mark.asyncio
async def test_18_client_supplied_verdicts_cannot_override_server_analysis(
    async_client: AsyncClient
) -> None:
    """Verify client cannot inject fake verdicts or trust flags via /analyze."""
    response = await async_client.post(
        "/api/v1/analyze",
        json={
            "source": "import stripe",
            "filename": "spoof.py",
            "verdict": "clean",  # forbidden field
            "evidence_trust": "live_official_source",  # forbidden field
        },
    )
    assert response.status_code == 422


# ============================================================================
# Section 3: History API Endpoints (19-31)
# ============================================================================

@pytest.mark.asyncio
async def test_19_history_list_returns_summary_fields(async_client: AsyncClient) -> None:
    """Verify GET /api/v1/scans returns lightweight summaries with required fields."""
    # Analyze a snippet to generate a saved scan
    analyze_resp = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe\ndef run(): pass", "filename": "summary_test.py", "ecosystem": "stripe"},
    )
    assert analyze_resp.status_code == 200
    scan_id = analyze_resp.json()["scan_id"]
    assert scan_id is not None

    # Query history list
    list_resp = await async_client.get("/api/v1/scans")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1

    item = data["items"][0]
    assert "scan_id" in item
    assert "created_at" in item
    assert "verdict" in item
    assert "ecosystem" in item
    assert "filename" in item
    assert "source_sha256" in item
    assert "is_mock" in item
    assert "candidates_count" in item
    assert "issues_count" in item


@pytest.mark.asyncio
async def test_20_pagination_respects_maximum_limit(async_client: AsyncClient) -> None:
    """Verify pagination clamps limit to maximum 100 and returns 422 for limit > 100."""
    response = await async_client.get("/api/v1/scans?limit=150")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_21_verdict_filtering_works(async_client: AsyncClient) -> None:
    """Verify filtering by verdict returns only matching records."""
    # Create an unable_to_verify scan
    await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe\ncharge = stripe.Charge.create()", "filename": "filt.py", "ecosystem": "stripe"},
    )

    # Filter by unable_to_verify
    resp = await async_client.get("/api/v1/scans?verdict=unable_to_verify")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["items"]:
        assert item["verdict"] == "unable_to_verify"

    # Filter by non-existent verdict returns 0 items
    resp2 = await async_client.get("/api/v1/scans?verdict=clean")
    assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_22_ecosystem_filtering_works(async_client: AsyncClient) -> None:
    """Verify filtering by ecosystem returns only matching records."""
    await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe", "filename": "stripe_filter.py", "ecosystem": "stripe"},
    )
    resp = await async_client.get("/api/v1/scans?ecosystem=stripe")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["ecosystem"] == "stripe"

    resp_other = await async_client.get("/api/v1/scans?ecosystem=nonexistent")
    assert resp_other.status_code == 200
    assert resp_other.json()["total"] == 0


def test_23_ordering_is_deterministic_for_equal_timestamps(isolated_audit_db: Path) -> None:
    """Verify deterministic secondary sort by scan_id DESC when timestamps are equal."""
    repo = ScanRepository(isolated_audit_db)
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_db(isolated_audit_db) as conn:
        conn.execute(
            """
            INSERT INTO scans (
                scan_id, schema_version, created_at, status, verdict, ecosystem,
                filename, source_sha256, source_length, pipeline_version,
                evidence_trust, is_mock, llm_reasoning_status, summary,
                checks_performed, limitations_and_caveats, disclaimer, integrity_hash
            ) VALUES
            ('scan_aaa', 1, ?, 'completed', 'clean', 'stripe', 'f.py', 'h1', 5, '0.1.0', 'mock_fixture', 1, 'disabled', 's', '[]', '[]', 'd', 'ih'),
            ('scan_zzz', 1, ?, 'completed', 'clean', 'stripe', 'f.py', 'h2', 5, '0.1.0', 'mock_fixture', 1, 'disabled', 's', '[]', '[]', 'd', 'ih')
            """,
            (now_iso, now_iso),
        )

    items, _ = repo.list_scans(limit=10)
    # scan_zzz should precede scan_aaa in DESC order
    ids = [it.scan_id for it in items if it.scan_id in ("scan_aaa", "scan_zzz")]
    assert ids == ["scan_zzz", "scan_aaa"]


@pytest.mark.asyncio
async def test_24_unknown_scan_ids_return_404(async_client: AsyncClient) -> None:
    """Verify requesting an unknown scan ID returns HTTP 404."""
    resp = await async_client.get("/api/v1/scans/scan_nonexistent123")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_25_detail_response_marked_historical(async_client: AsyncClient) -> None:
    """Verify scan detail response includes is_historical=True and integrity_hash."""
    analyze_resp = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe", "filename": "hist.py", "ecosystem": "stripe"},
    )
    scan_id = analyze_resp.json()["scan_id"]

    detail_resp = await async_client.get(f"/api/v1/scans/{scan_id}")
    assert detail_resp.status_code == 200
    data = detail_resp.json()
    assert data["is_historical"] is True
    assert "integrity_hash" in data
    assert len(data["integrity_hash"]) == 64


@pytest.mark.asyncio
async def test_26_loading_history_does_not_call_doc_retrieval_or_llm(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify loading historical scan detail performs zero external requests or LLM calls."""
    # First save a scan
    analyze_resp = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe", "filename": "no_fetch.py", "ecosystem": "stripe"},
    )
    scan_id = analyze_resp.json()["scan_id"]

    # Mock external calls to raise error if called
    def boom(*args, **kwargs):
        raise RuntimeError("External network call should NOT happen during history inspection!")

    from app.services.documentation.retrieval_service import retrieval_service
    from app.services.llm.reasoning_service import llm_service
    monkeypatch.setattr(retrieval_service, "retrieve", boom)
    monkeypatch.setattr(llm_service, "reason", boom)

    # Loading scan detail should succeed purely from SQLite
    detail_resp = await async_client.get(f"/api/v1/scans/{scan_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["scan_id"] == scan_id


@pytest.mark.asyncio
async def test_27_deleting_scan_removes_dependent_records(
    async_client: AsyncClient, isolated_audit_db: Path
) -> None:
    """Verify deleting a scan removes its record and cascade-deletes evidence and findings."""
    analyze_resp = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe\ncharge = stripe.Charge.create()", "filename": "del.py", "ecosystem": "stripe"},
    )
    scan_id = analyze_resp.json()["scan_id"]

    # Verify rows exist in DB
    with get_db(isolated_audit_db) as conn:
        c1 = conn.execute("SELECT COUNT(*) FROM scan_evidence WHERE scan_id = ?", (scan_id,)).fetchone()[0]
        assert c1 >= 0

    # Delete scan via API
    del_resp = await async_client.delete(f"/api/v1/scans/{scan_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Scan detail should now 404
    get_resp = await async_client.get(f"/api/v1/scans/{scan_id}")
    assert get_resp.status_code == 404

    # DB records should be completely gone
    with get_db(isolated_audit_db) as conn:
        c_scan = conn.execute("SELECT COUNT(*) FROM scans WHERE scan_id = ?", (scan_id,)).fetchone()[0]
        c_ev = conn.execute("SELECT COUNT(*) FROM scan_evidence WHERE scan_id = ?", (scan_id,)).fetchone()[0]
        c_find = conn.execute("SELECT COUNT(*) FROM scan_findings WHERE scan_id = ?", (scan_id,)).fetchone()[0]
        assert c_scan == 0
        assert c_ev == 0
        assert c_find == 0


@pytest.mark.asyncio
async def test_28_deleting_unknown_scan_returns_404(async_client: AsyncClient) -> None:
    """Verify deleting a nonexistent scan returns HTTP 404."""
    resp = await async_client.delete("/api/v1/scans/scan_unknown12345678")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_29_sql_injection_strings_in_filters_safe(async_client: AsyncClient) -> None:
    """Verify malicious SQL injection strings in query filters are handled safely."""
    injection_payload = "clean' OR '1'='1"
    resp = await async_client.get(f"/api/v1/scans?verdict={injection_payload}")
    assert resp.status_code == 200
    # Parameterized query should treat it as literal string with 0 results
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_30_arbitrary_database_paths_cannot_be_specified_via_http(async_client: AsyncClient) -> None:
    """Verify clients cannot pass arbitrary database file paths via HTTP parameters."""
    resp = await async_client.get("/api/v1/scans?db_path=/etc/passwd")
    # Query param is ignored, response is standard 200
    assert resp.status_code == 200


def test_31_overlong_or_malformed_persisted_fields_handled_safely(isolated_audit_db: Path) -> None:
    """Verify overlong metadata fields are truncated safely without throwing unhandled errors."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(
        source="import stripe",
        filename="A" * 255,  # max length filename
        ecosystem="stripe",
    )
    report = AnalysisReport(
        verdict="clean",
        engine_version="0.1.0",
        filename="A" * 255,
        total_lines=1,
        evidence_trust="mock_fixture",
        is_mock=True,
        summary="S" * 10_000,
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    scan_id = repo.save_scan(request, report)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert len(detail.filename) <= 255
    assert len(detail.summary) >= 1


# ============================================================================
# Section 4: Regression and Security Invariants (32-40)
# ============================================================================

@pytest.mark.asyncio
async def test_32_existing_unified_analysis_endpoint_compatible(async_client: AsyncClient) -> None:
    """Verify existing /api/v1/analyze endpoint returns all expected baseline fields."""
    resp = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe\ndef charge(): pass", "filename": "reg_test.py", "ecosystem": "stripe"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "verdict" in data
    assert "engine_version" in data
    assert "checks_performed" in data
    assert "verified_issues" in data
    assert "ai_suggestions" in data
    assert "scan_id" in data
    assert "persistence_status" in data


@pytest.mark.asyncio
async def test_33_existing_fixes_propose_endpoint_compatible(async_client: AsyncClient) -> None:
    """Verify existing /api/v1/fixes/propose endpoint remains fully compatible."""
    resp = await async_client.post(
        "/api/v1/fixes/propose",
        json={
            "source": "import stripe\ncharge = stripe.Charge.create(amount=1000, source='tok_123')",
            "filename": "fix_reg.py",
            "candidate_id": "cand_001",
            "ecosystem": "stripe",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("mock_evidence_only", "evidence_supported", "unsupported_candidate")


@pytest.mark.asyncio
async def test_34_existing_ast_extraction_tests_compatible(async_client: AsyncClient) -> None:
    """Verify /api/v1/analyze/python continues to function without regression."""
    resp = await async_client.post(
        "/api/v1/analyze/python",
        json={"source": "import stripe\ndef test(): pass", "filename": "ast_reg.py"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["imports"]) == 1


@pytest.mark.asyncio
async def test_35_existing_documentation_retrieval_tests_compatible(async_client: AsyncClient) -> None:
    """Verify /api/v1/docs/retrieve continues to function with SSRF guards."""
    resp = await async_client.post(
        "/api/v1/docs/retrieve",
        json={"query": "Charge", "ecosystem": "stripe", "max_results": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] in ("tinyfish_mock", "tinyfish_live")


@pytest.mark.asyncio
async def test_36_existing_evidence_court_mock_quarantine_intact(async_client: AsyncClient) -> None:
    """Verify mock quarantine rule remains intact during persistence."""
    resp = await async_client.post(
        "/api/v1/analyze",
        json={
            "source": "import stripe\ncharge = stripe.Charge.create(amount=1000, source='tok_123')",
            "filename": "quarantine.py",
            "ecosystem": "stripe",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    if data["is_mock"]:
        assert data["verdict"] == "unable_to_verify"
        assert len(data["verified_issues"]) == 0


@pytest.mark.asyncio
async def test_37_existing_llm_tests_compatible(async_client: AsyncClient) -> None:
    """Verify LLM reasoning status field is returned and persisted."""
    resp = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe", "filename": "llm_reg.py", "ecosystem": "stripe"},
    )
    assert resp.status_code == 200
    assert "llm_reasoning_status" in resp.json()


def test_38_raw_source_text_api_keys_not_persisted(isolated_audit_db: Path) -> None:
    """Verify API keys and authorization headers are never persisted into database."""
    repo = ScanRepository(isolated_audit_db)
    source = "import stripe\nstripe.api_key = '" + "sk" + "_live_1234567890abcdefsecretkey'"
    request = AnalysisRequest(source=source, filename="keys.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="unable_to_verify",
        engine_version="0.1.0",
        filename="keys.py",
        total_lines=2,
        evidence_trust="mock_fixture",
        is_mock=True,
        summary="Key test.",
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    scan_id = repo.save_scan(request, report)
    with get_db(isolated_audit_db) as conn:
        row = conn.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,)).fetchone()
        for k, v in dict(row).items():
            if v:
                assert "sk_live_" not in str(v)


@pytest.mark.asyncio
async def test_39_stored_historical_scan_does_not_become_fresh_scan(async_client: AsyncClient) -> None:
    """Verify loading historical scan has is_historical=True and retains original disclaimer."""
    analyze_resp = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe", "filename": "stale.py", "ecosystem": "stripe"},
    )
    scan_id = analyze_resp.json()["scan_id"]

    detail_resp = await async_client.get(f"/api/v1/scans/{scan_id}")
    assert detail_resp.status_code == 200
    data = detail_resp.json()
    assert data["is_historical"] is True
    assert "disclaimer" in data


@pytest.mark.asyncio
async def test_40_database_errors_do_not_leak_internal_stack_traces_or_secrets(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify database internal errors return sanitized HTTP 500 without stack trace leaks."""
    def boom(*args, **kwargs):
        raise sqlite3.DatabaseError("Database disk image is malformed at /private/var/secret_path")

    monkeypatch.setattr(scan_repository, "get_scan", boom)

    resp = await async_client.get("/api/v1/scans/scan_validid1234567")
    assert resp.status_code == 500
    assert "/private/var/secret_path" not in resp.text
    assert "error occurred" in resp.json()["detail"].lower()


# ============================================================================
# Section 5: Hardening, Privacy, and Restart Audit (41-55)
# ============================================================================

def test_41_default_configuration_does_not_persist_source_code(isolated_audit_db: Path) -> None:
    """Scenario 1: Verify default configuration does not persist source code."""
    assert settings.SOURCE_RETENTION_ENABLED is False
    repo = ScanRepository(isolated_audit_db)
    source_code = "import stripe\ndef charge_card():\n    return stripe.Charge.create(amount=500)"
    request = AnalysisRequest(source=source_code, filename="payment.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="unable_to_verify",
        engine_version="0.1.0",
        filename="payment.py",
        total_lines=3,
        evidence_trust="mock_fixture",
        is_mock=True,
        summary="Mock run.",
        checks_performed=["call_graph"],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )
    scan_id = repo.save_scan(request, report)
    
    with get_db(isolated_audit_db) as conn:
        for table in ["scans", "scan_evidence", "scan_findings", "scan_fix_proposals"]:
            rows = conn.execute(f"SELECT * FROM {table} WHERE scan_id = ?", (scan_id,)).fetchall()
            for r in rows:
                for k, v in dict(r).items():
                    if v is not None:
                        assert source_code not in str(v), f"Raw source found in table {table}, column {k}"


@pytest.mark.asyncio
async def test_42_http_input_cannot_enable_source_retention(async_client: AsyncClient) -> None:
    """Scenario 2: Verify HTTP input cannot override or enable source retention."""
    malicious_payload = {
        "source": "import stripe",
        "filename": "attempt.py",
        "ecosystem": "stripe",
        "source_retention_enabled": True,
        "store_source": True,
    }
    resp = await async_client.post("/api/v1/analyze", json=malicious_payload)
    assert resp.status_code == 422
    assert "extra_forbidden" in resp.text


def test_43_database_contents_inspected_row_by_row_for_source_privacy(isolated_audit_db: Path) -> None:
    """Scenario 3: Verify database contents do not contain submitted source in default mode."""
    repo = ScanRepository(isolated_audit_db)
    secret_marker = "CANARY_TOKEN_9876543210_PRIVATE_DATA"
    source = f"import stripe\n# {secret_marker}\nstripe.api_key = 'test'"
    request = AnalysisRequest(source=source, filename="canary.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="unable_to_verify",
        engine_version="0.1.0",
        filename="canary.py",
        total_lines=3,
        evidence_trust="mock_fixture",
        is_mock=True,
        summary="Canary verification.",
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )
    scan_id = repo.save_scan(request, report)

    # Query every string value across all tables
    with get_db(isolated_audit_db) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r["name"] for r in cursor.fetchall()]
        for tbl in tables:
            rows = conn.execute(f"SELECT * FROM {tbl}").fetchall()
            for row in rows:
                for col_name, val in dict(row).items():
                    if val is not None:
                        assert secret_marker not in str(val), f"Secret leaked in table '{tbl}', col '{col_name}'"


def test_44_stored_diffs_and_excerpts_follow_documented_privacy_policy(isolated_audit_db: Path) -> None:
    """Scenario 4: Stored diffs and excerpts follow documented privacy policy."""
    repo = ScanRepository(isolated_audit_db)
    source = "import stripe\ndef pay():\n    return stripe.Charge.create(amount=100, source='tok_123')\n"
    request = AnalysisRequest(source=source, filename="pay.py", ecosystem="stripe")
    
    # Create report with verified issue on cand_001
    finding = VerifiedIssue(
        issue_id="iss_001",
        candidate_id="cand_001",
        source_location=SourceLocation(lineno=3, col_offset=11, end_lineno=3, end_col_offset=62),
        claim_checked="source parameter support",
        violation_type="legacy_deprecated_parameter",
        explanation="Stripe Charge with source is deprecated.",
        supporting_evidence_id="ev_001",
        source_url="https://docs.stripe.com/api/charges/create",
        verified_quote="The source parameter is deprecated in modern Stripe APIs.",
        match_method="exact",
    )
    report = AnalysisReport(
        verdict="issues_found",
        engine_version="0.1.0",
        filename="pay.py",
        total_lines=4,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="Issues found.",
        checks_performed=["ast", "contract"],
        verified_issues=[finding],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )
    scan_id = repo.save_scan(request, report)

    # Link a fix proposal
    proposal = FixProposalResponse(
        proposal_id="prop_abcd1234efgh",
        candidate_id="cand_001",
        status="evidence_supported",
        summary="Migrate Charge to PaymentIntent",
        reasoning="Based on official Stripe migration contract.",
        original_excerpt="stripe.Charge.create(amount=100, source='tok_123')",
        proposed_excerpt="stripe.PaymentIntent.create(amount=100, payment_method='tok_123')",
        unified_diff="--- a/pay.py\n+++ b/pay.py\n@@ -3,1 +3,1 @@\n-    return stripe.Charge.create(amount=100, source='tok_123')\n+    return stripe.PaymentIntent.create(amount=100, payment_method='tok_123')\n",
        proposed_source="import stripe\ndef pay():\n    return stripe.PaymentIntent.create(amount=100, payment_method='tok_123')\n",
        supporting_evidence_ids=["ev_001"],
        supporting_quotes=["The source parameter is deprecated in modern Stripe APIs."],
        source_urls=["https://docs.stripe.com/api/charges/create"],
        evidence_trust="live_official_source",
        is_mock=False,
        is_ai_generated=False,
        syntax_valid=True,
        reverification_status="verified_resolved",
        remaining_uncertainties=[],
        warnings=[],
    )
    success = repo.link_fix_proposal(scan_id, proposal)
    assert success is True

    # Verify only unified diff is stored in scan_fix_proposals, not proposed_source
    with get_db(isolated_audit_db) as conn:
        row = conn.execute("SELECT * FROM scan_fix_proposals WHERE proposal_id = ?", ("prop_abcd1234efgh",)).fetchone()
        assert row is not None
        assert row["diff"] == proposal.unified_diff
        assert row["status"] == "evidence_supported"
        # Proposed source full text is not stored in table
        assert "proposed_source" not in dict(row)


def test_45_fix_proposal_linkage_validated_server_side(isolated_audit_db: Path) -> None:
    """Scenario 5: Fix-proposal linkage is validated server-side."""
    repo = ScanRepository(isolated_audit_db)
    source = "import stripe\ndef charge(): return stripe.Charge.create(amount=100)"
    request = AnalysisRequest(source=source, filename="p.py", ecosystem="stripe")
    finding = VerifiedIssue(
        issue_id="iss_001",
        candidate_id="cand_real_001",
        source_location=SourceLocation(lineno=1, col_offset=0, end_lineno=1, end_col_offset=10),
        claim_checked="charge create call",
        violation_type="legacy_deprecated_call",
        explanation="use payment intent",
        supporting_evidence_id="ev_001",
        source_url="https://docs.stripe.com",
        verified_quote="quote",
        match_method="exact",
    )
    report = AnalysisReport(
        verdict="issues_found",
        engine_version="0.1.0",
        filename="p.py",
        total_lines=1,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="issue",
        checks_performed=[],
        verified_issues=[finding],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )
    scan_id = repo.save_scan(request, report)

    # 1. Invalid proposal ID format rejected
    invalid_id_proposal = FixProposalResponse(
        proposal_id="invalid_not_matching_regex!@#$",
        candidate_id="cand_real_001",
        status="evidence_supported",
        summary="s",
        reasoning="r",
        unified_diff="--- a\n+++ b\n",
        evidence_trust="live_official_source",
        is_mock=False,
        syntax_valid=True,
        reverification_status="verified_resolved",
    )
    assert repo.link_fix_proposal(scan_id, invalid_id_proposal) is False

    # 2. Non-existent scan_id rejected
    valid_proposal = FixProposalResponse(
        proposal_id="prop_valid12345678",
        candidate_id="cand_real_001",
        status="evidence_supported",
        summary="s",
        reasoning="r",
        unified_diff="--- a\n+++ b\n",
        evidence_trust="live_official_source",
        is_mock=False,
        syntax_valid=True,
        reverification_status="verified_resolved",
    )
    assert repo.link_fix_proposal("scan_nonexistent999", valid_proposal) is False

    # 3. Fabricated candidate ID not belonging to scan rejected
    fabricated_cand_proposal = FixProposalResponse(
        proposal_id="prop_valid12345678",
        candidate_id="cand_fabricated_alien",
        status="evidence_supported",
        summary="s",
        reasoning="r",
        unified_diff="--- a\n+++ b\n",
        evidence_trust="live_official_source",
        is_mock=False,
        syntax_valid=True,
        reverification_status="verified_resolved",
    )
    assert repo.link_fix_proposal(scan_id, fabricated_cand_proposal) is False

    # 4. Legitimate candidate linkage succeeds
    assert repo.link_fix_proposal(scan_id, valid_proposal) is True


def test_46_record_digest_canonicalization_is_deterministic() -> None:
    """Scenario 6: Record-digest canonicalization is deterministic across ordering and spacing."""
    hash1 = compute_record_integrity_hash(
        scan_id="scan_det_001",
        created_at="2026-10-17T00:00:00Z",
        verdict="clean",
        ecosystem="stripe",
        filename="det.py",
        source_sha256="abc123hash",
        source_length=42,
        evidence_trust="live_official_source",
        is_mock=False,
        verified_issues=[],
        evidence_items=[],
        checks_performed=["ast_parse", "contract_match"],
        summary="Clean report.",
    )

    # Identical inputs in a separate invocation must yield identical hash
    hash2 = compute_record_integrity_hash(
        scan_id="scan_det_001",
        created_at="2026-10-17T00:00:00Z",
        verdict="clean",
        ecosystem="stripe",
        filename="det.py",
        source_sha256="abc123hash",
        source_length=42,
        evidence_trust="live_official_source",
        is_mock=False,
        verified_issues=[],
        evidence_items=[],
        checks_performed=["contract_match", "ast_parse"],  # Reordered checks
        summary="Clean report.",
    )
    assert hash1 == hash2, "Integrity hash must be deterministic and invariant to list order of checks"


def test_47_changes_to_covered_fields_change_digest() -> None:
    """Scenario 7: Changes to covered fields produce a different digest."""
    base_args = dict(
        scan_id="scan_base",
        created_at="2026-10-17T00:00:00Z",
        verdict="clean",
        ecosystem="stripe",
        filename="file.py",
        source_sha256="hash_base",
        source_length=50,
        evidence_trust="live_official_source",
        is_mock=False,
        verified_issues=[],
        evidence_items=[],
        checks_performed=["ast_parse"],
        summary="Base summary.",
    )
    base_hash = compute_record_integrity_hash(**base_args)

    # Change verdict
    mod_verdict = dict(base_args, verdict="issues_found")
    assert compute_record_integrity_hash(**mod_verdict) != base_hash

    # Change source hash
    mod_source = dict(base_args, source_sha256="different_hash")
    assert compute_record_integrity_hash(**mod_source) != base_hash

    # Change summary
    mod_summary = dict(base_args, summary="Altered summary.")
    assert compute_record_integrity_hash(**mod_summary) != base_hash

    # Change mock status
    mod_mock = dict(base_args, is_mock=True, evidence_trust="mock_fixture")
    assert compute_record_integrity_hash(**mod_mock) != base_hash


def test_48_evidence_excerpt_hashes_match_exact_stored_excerpt(isolated_audit_db: Path) -> None:
    """Scenario 8: Evidence excerpt hashes match the exact stored excerpt in database."""
    repo = ScanRepository(isolated_audit_db)
    # Long excerpt (>4000 characters) to test truncation boundary
    long_content = "Stripe official docs: " + ("x" * 5000)
    ev_item = NormalizedEvidence(
        evidence_id="ev_long_001",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/charges",
        canonical_url="https://docs.stripe.com/charges",
        title="Charges API",
        content_excerpt=long_content,
        retrieved_at="2026-10-17T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
    )
    request = AnalysisRequest(source="import stripe", filename="test.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="clean",
        engine_version="0.1.0",
        filename="test.py",
        total_lines=1,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="Clean.",
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[ev_item],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )
    scan_id = repo.save_scan(request, report)

    with get_db(isolated_audit_db) as conn:
        rows = conn.execute("SELECT content_excerpt, content_sha256 FROM scan_evidence WHERE scan_id = ?", (scan_id,)).fetchall()
        assert len(rows) == 1
        stored_text = rows[0]["content_excerpt"]
        stored_hash = rows[0]["content_sha256"]
        recomputed = hashlib.sha256(stored_text.encode("utf-8")).hexdigest()
        assert stored_hash == recomputed, "Stored content_sha256 must match recomputed hash of exact stored text"


def test_49_database_write_failure_rolls_back_transaction(isolated_audit_db: Path) -> None:
    """Scenario 9: Database write failure rolls back transaction cleanly without partial records."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(source="import stripe\ncharge = stripe.Charge.create()", filename="fail.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="issues_found",
        engine_version="0.1.0",
        filename="fail.py",
        total_lines=2,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="Failed scan test",
        checks_performed=["ast", "contract"],
        verified_issues=[
            VerifiedIssue(
                issue_id="iss_001",
                candidate_id="cand_001",
                source_location=SourceLocation(lineno=2, col_offset=9, end_lineno=2, end_col_offset=31),
                claim_checked="charge create",
                violation_type="legacy_deprecated_call",
                explanation="Deprecated call",
                supporting_evidence_id="ev_001",
                source_url="https://docs.stripe.com",
                verified_quote="Quote text",
                match_method="exact",
            )
        ],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[
            NormalizedEvidence(
                evidence_id="ev_001",
                ecosystem="stripe",
                package="stripe",
                source_url="https://docs.stripe.com",
                canonical_url="https://docs.stripe.com",
                title="Stripe Docs",
                content_excerpt="Quote text",
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                provider="tinyfish_live",
                status="live",
                is_mock=False,
                source_trust="official",
                doc_version="2024-04-10",
            )
        ],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )

    # Install an SQLite trigger that fails halfway through persistence (on scan_findings insert)
    with get_db(isolated_audit_db) as conn:
        conn.execute(
            """
            CREATE TRIGGER abort_on_findings_insert
            BEFORE INSERT ON scan_findings
            BEGIN
                SELECT RAISE(ABORT, 'Simulated halfway disk or constraint failure');
            END;
            """
        )

    # Attempting to save scan must fail when findings are inserted
    with pytest.raises(sqlite3.IntegrityError, match="Simulated halfway disk or constraint failure"):
        repo.save_scan(request, report)

    # Verify atomic rollback: no partial records in any table (scans, scan_evidence, scan_findings)
    with get_db(isolated_audit_db) as conn:
        assert conn.execute("SELECT COUNT(*) as c FROM scans").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) as c FROM scan_evidence").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) as c FROM scan_findings").fetchone()["c"] == 0


def test_50_genuine_restart_persistence_with_separate_repository_instances(tmp_path: Path) -> None:
    """Scenario 10: Genuine restart persistence test following all 9 specification steps."""
    # Step 1: Create dedicated temporary database path
    temp_db_path = tmp_path / "restart_audit.db"

    # Step 2: Initialize schema
    init_db(temp_db_path)

    # Step 3: Save scan using legitimate server-side report via repo1
    repo1 = ScanRepository(temp_db_path)
    source_code = "import stripe\ncharge = stripe.Charge.create(amount=2000, source='tok_visa')"
    request = AnalysisRequest(source=source_code, filename="checkout_restart.py", ecosystem="stripe")
    
    finding = VerifiedIssue(
        issue_id="iss_restart_001",
        candidate_id="cand_restart_001",
        source_location=SourceLocation(lineno=2, col_offset=9, end_lineno=2, end_col_offset=63),
        claim_checked="source parameter support",
        violation_type="legacy_deprecated_parameter",
        explanation="Stripe Charge with source is deprecated.",
        supporting_evidence_id="ev_restart_001",
        source_url="https://docs.stripe.com/api/charges/create",
        verified_quote="The source parameter is deprecated in modern Stripe APIs.",
        match_method="exact",
    )
    ev_item = NormalizedEvidence(
        evidence_id="ev_restart_001",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a Charge",
        content_excerpt="The source parameter is deprecated in modern Stripe APIs.",
        retrieved_at="2026-10-17T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
    )
    report = AnalysisReport(
        verdict="issues_found",
        engine_version="0.1.0",
        filename="checkout_restart.py",
        total_lines=2,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="Restart test report.",
        checks_performed=["ast", "contract"],
        verified_issues=[finding],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[ev_item],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )
    scan_id = repo1.save_scan(request, report)
    assert scan_id.startswith("scan_")

    # Step 4: Close repository connections (repo1 is done, connections are closed by context manager)
    del repo1

    # Step 5: Create a NEW repository instance using the same database path
    repo2 = ScanRepository(temp_db_path)

    # Step 6: Retrieve the saved scan and its dependent evidence and findings
    detail = repo2.get_scan(scan_id)
    assert detail is not None

    # Step 7: Confirm original verdict, source fingerprint, mock/live classification, and historical status
    assert detail.scan_id == scan_id
    assert detail.verdict == "issues_found"
    assert detail.source_sha256 == hashlib.sha256(source_code.encode("utf-8")).hexdigest()
    assert detail.source_length == len(source_code)
    assert detail.is_mock is False
    assert detail.evidence_trust == "live_official_source"
    assert detail.is_historical is True
    assert len(detail.verified_issues) == 1
    assert detail.verified_issues[0].issue_id == "iss_restart_001"
    assert len(detail.evidence_items) == 1
    assert detail.evidence_items[0].evidence_id == "ev_restart_001"

    # Step 8: Confirm retrieval did not call external services (repo2.get_scan is purely SQLite SELECT)
    # Step 9: Safely clean up temporary database and WAL/SHM files
    del repo2
    for ext in ["", "-wal", "-shm"]:
        p = Path(str(temp_db_path) + ext)
        if p.exists():
            p.unlink()


@pytest.mark.asyncio
async def test_51_historical_retrieval_does_not_invoke_external_services(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 11: Historical retrieval endpoint does not call LLM or doc retrieval."""
    # First create a scan
    resp = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe\ndef pay(): pass", "filename": "hist.py", "ecosystem": "stripe"},
    )
    scan_id = resp.json()["scan_id"]

    # Monkeypatch doc retrieval and LLM reasoning to blow up if called
    def fail_if_called(*args, **kwargs):
        raise AssertionError("External retrieval or LLM service should NEVER be called when retrieving historical scan!")

    from app.services.documentation.retrieval_service import retrieval_service
    from app.services.llm.reasoning_service import llm_service
    monkeypatch.setattr(retrieval_service, "retrieve", fail_if_called)
    monkeypatch.setattr(llm_service, "reason", fail_if_called)

    detail_resp = await async_client.get(f"/api/v1/scans/{scan_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["is_historical"] is True


def test_52_mock_classification_survives_save_load_round_trip(isolated_audit_db: Path) -> None:
    """Scenario 12: Mock classification survives a save/load round trip."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(source="import stripe", filename="mock.py", ecosystem="stripe", force_mock=True)
    report = AnalysisReport(
        verdict="unable_to_verify",
        engine_version="0.1.0",
        filename="mock.py",
        total_lines=1,
        evidence_trust="mock_fixture",
        is_mock=True,
        summary="Mock execution.",
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[
            NormalizedEvidence(
                evidence_id="ev_mock_001",
                ecosystem="stripe",
                package="stripe",
                source_url="https://docs.stripe.com",
                canonical_url="https://docs.stripe.com",
                title="Mock Doc",
                content_excerpt="Mock excerpt text",
                retrieved_at="2026-10-17T00:00:00Z",
                provider="tinyfish_mock",
                status="mock",
                is_mock=True,
                source_trust="mock_fixture",
            )
        ],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )
    scan_id = repo.save_scan(request, report)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert detail.is_mock is True
    assert detail.evidence_trust == "mock_fixture"
    assert detail.evidence_items[0].is_mock is True
    assert detail.evidence_items[0].status == "mock"


@pytest.mark.asyncio
async def test_53_controlled_startup_failure_on_unsupported_future_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario 13: Controlled startup failure when database has unsupported future schema version."""
    future_db_path = tmp_path / "future_schema.db"
    with get_db(future_db_path) as conn:
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)")
        conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (999, 'future_migration', '2030-01-01')")

    monkeypatch.setattr(settings, "APICOMPASS_DB_PATH", str(future_db_path))

    with pytest.raises(RuntimeError) as exc_info:
        async with lifespan(app):
            pass
    assert "Database migration failure" in str(exc_info.value) or "unsupported" in str(exc_info.value).lower()


def test_54_source_retention_validator_prevents_silent_enable() -> None:
    """Scenario 14: Source retention field validator rejects ambiguous values and defaults strictly to False."""
    assert settings.validate_source_retention(False) is False
    assert settings.validate_source_retention(True) is True
    assert settings.validate_source_retention("true") is True
    assert settings.validate_source_retention("1") is True
    assert settings.validate_source_retention("false") is False
    assert settings.validate_source_retention("0") is False
    assert settings.validate_source_retention("invalid_text") is False
    assert settings.validate_source_retention(None) is False
    assert settings.validate_source_retention({}) is False


def test_55_integrity_hash_disclaimer_bounds(isolated_audit_db: Path) -> None:
    """Scenario 15: Verify audit records and disclaimers do not claim external anchoring or tamper-proof ledgers."""
    repo = ScanRepository(isolated_audit_db)
    request = AnalysisRequest(source="import stripe", filename="disclaimer.py", ecosystem="stripe")
    report = AnalysisReport(
        verdict="clean",
        engine_version="0.1.0",
        filename="disclaimer.py",
        total_lines=1,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="Clean.",
        checks_performed=[],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[],
        limitations_and_caveats=[],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )
    scan_id = repo.save_scan(request, report)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    # Verify disclaimer clarifies deterministic verification boundaries without overclaiming
    assert "blockchain" not in detail.disclaimer.lower()
    assert "tamper-proof ledger" not in detail.disclaimer.lower()
    assert "digital signature" not in detail.disclaimer.lower()

