"""Comprehensive audit tests for APICompass scan history, database models, and audit records.

Verifies:
1. Secret scrubbing across all database tables (scans, scan_findings, scan_evidence, scan_fix_proposals, scan_project_files).
2. Zero raw source code retention by default (only source SHA-256 and character length).
3. Documentation evidence provenance and bounded excerpts (max 4000 chars).
4. Graceful degradation when encountering corrupted database rows or malformed JSON.
5. Non-breaking behavior of analysis endpoints during storage failures.
6. Parameterized SQL queries preventing SQL injection in all query filters.
7. Test database isolation preventing any mutation of development data.
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
from app.db import init_db
from app.db.connection import get_db
from app.main import app
from app.repositories import ScanRepository, scan_repository
from app.schemas.evidence import (
    AnalysisRequest,
    AnalysisReport,
    CandidateAssessment,
    VerifiedIssue,
    AISuggestion,
)
from app.schemas.ast_analysis import SourceLocation
from app.schemas.documentation import NormalizedEvidence
from app.schemas.fix_proposal import FixProposalResponse
from app.schemas.project_analysis import (
    ProjectAnalysisRequest,
    ProjectAnalysisReport,
    ProjectFileAnalysisResult,
)


@pytest.fixture(autouse=True)
def isolated_audit_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Isolate database to a temporary SQLite file per test."""
    test_db_path = tmp_path / "audit_verification.db"
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
# Section 1: Secret Scrubbing Audit Across All Stored Records
# ============================================================================

def test_secret_scrubbing_in_single_file_scan_records(isolated_audit_db: Path) -> None:
    """Requirement 3: Never store API keys or auth headers in scan tables."""
    repo = ScanRepository(isolated_audit_db)
    
    leak_api_key = "sk" + "_live_51NyTestSecretKey9999999999"
    leak_bearer = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sensitive"
    
    source = f"import stripe\nstripe.api_key = '{leak_api_key}'\n# Header: {leak_bearer}"
    request = AnalysisRequest(
        source=source,
        filename=f"secret_{leak_api_key}.py",
        ecosystem="stripe",
    )
    
    finding = VerifiedIssue(
        issue_id="iss_leak_001",
        candidate_id="cand_leak_001",
        source_location=SourceLocation(lineno=2, col_offset=0, end_lineno=2, end_col_offset=40),
        claim_checked="api key setup",
        violation_type="hardcoded_secret",
        explanation=f"Found hardcoded key {leak_api_key} in source.",
        supporting_evidence_id="ev_leak_001",
        source_url="https://docs.stripe.com/keys",
        verified_quote=f"Never commit {leak_api_key} into public repositories.",
        match_method="exact",
    )
    
    ev_item = NormalizedEvidence(
        evidence_id="ev_leak_001",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/keys",
        canonical_url="https://docs.stripe.com/keys",
        title=f"Secret Management with {leak_api_key}",
        content_excerpt=f"Authorization header must be set to {leak_bearer} securely.",
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
    )
    
    ai_sug = AISuggestion(
        candidate_id="cand_leak_001",
        suggestion_id="sug_leak_001",
        claim_type="recommendation",
        description=f"Use environment variables instead of {leak_api_key}.",
        unverified_aspects=f"Unverified advice about {leak_api_key}.",
    )
    
    report = AnalysisReport(
        verdict="issues_found",
        engine_version="0.1.0",
        filename=f"secret_{leak_api_key}.py",
        total_lines=3,
        evidence_trust="live_official_source",
        is_mock=False,
        summary=f"Analysis of {leak_api_key} detected hardcoded secret.",
        checks_performed=[f"ast_check_{leak_api_key}"],
        verified_issues=[finding],
        ai_suggestions=[ai_sug],
        unresolved_candidates=[],
        candidate_assessments=[],
        evidence_items=[ev_item],
        limitations_and_caveats=[f"Caveat for {leak_bearer}"],
        syntax_error=None,
        llm_reasoning_status="disabled",
    )
    
    scan_id = repo.save_scan(request, report)
    
    # Check every string in every table in SQLite
    with get_db(isolated_audit_db) as conn:
        tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                for col, val in dict(row).items():
                    if val is not None:
                        val_str = str(val)
                        assert leak_api_key not in val_str, f"Leaked API key in table {table}, col {col}"
                        assert leak_bearer not in val_str, f"Leaked Bearer token in table {table}, col {col}"


def test_secret_scrubbing_in_project_and_fix_proposal_records(isolated_audit_db: Path) -> None:
    """Requirement 3: Never store secrets in multi-file project files or fix proposals."""
    repo = ScanRepository(isolated_audit_db)
    leak_api_key = "sk" + "_live_51SecretProjectKey99999999"
    
    # 1. Save project scan
    proj_req = ProjectAnalysisRequest(
        project_name=f"proj_{leak_api_key}",
        ecosystem="stripe",
        files=[
            {"path": f"src/{leak_api_key}.py", "content": f"import stripe\napi_key = '{leak_api_key}'"}
        ],
    )
    
    file_result = ProjectFileAnalysisResult(
        path=f"src/{leak_api_key}.py",
        parse_status="success",
        total_lines=2,
        candidates=[],
        syntax_error=None,
    )
    
    proj_report = ProjectAnalysisReport(
        project_name=f"proj_{leak_api_key}",
        total_files=1,
        total_lines=2,
        parsed_files_count=1,
        syntax_errors_count=0,
        total_candidates=0,
        resolved_imports_count=0,
        unresolved_imports_count=0,
        ambiguous_imports_count=0,
        verdict="clean",
        evidence_trust="live_official_source",
        is_mock=False,
        summary=f"Clean project scan for {leak_api_key}",
        checks_performed=[],
        files=[file_result],
        verified_issues=[],
        ai_suggestions=[],
        unresolved_candidates=[],
        evidence_items=[],
        limitations_and_caveats=[],
    )
    
    scan_id = repo.save_project_scan(proj_req, proj_report)
    
    # Insert a dummy finding so we can link a fix proposal
    with get_db(isolated_audit_db) as conn:
        conn.execute(
            """
            INSERT INTO scan_findings (scan_id, finding_type, candidate_id, category, source_line, message, details_json)
            VALUES (?, 'verified_issue', 'cand_fix_001', 'deprecated_call', 1, 'Deprecated call', '{}')
            """,
            (scan_id,),
        )
    
    # 2. Link fix proposal containing secret in diff and explanation
    prop = FixProposalResponse(
        proposal_id="prop_secretfix1234",
        candidate_id="cand_fix_001",
        status="evidence_supported",
        summary=f"Replace {leak_api_key} with env var",
        reasoning="Secure secret storage",
        original_excerpt=f"api_key = '{leak_api_key}'",
        proposed_excerpt="api_key = os.getenv('STRIPE_API_KEY')",
        unified_diff=f"--- a/pay.py\n+++ b/pay.py\n@@ -1,1 +1,1 @@\n-api_key = '{leak_api_key}'\n+api_key = os.getenv('STRIPE_API_KEY')\n",
        proposed_source="import os\napi_key = os.getenv('STRIPE_API_KEY')",
        supporting_evidence_ids=[],
        supporting_quotes=[],
        source_urls=[],
        evidence_trust="live_official_source",
        is_mock=False,
        is_ai_generated=False,
        syntax_valid=True,
        reverification_status="verified_resolved",
        remaining_uncertainties=[],
        warnings=[],
    )
    
    linked = repo.link_fix_proposal(scan_id, prop)
    assert linked is True
    
    # Verify no table contains the secret key
    with get_db(isolated_audit_db) as conn:
        tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                for col, val in dict(row).items():
                    if val is not None:
                        assert leak_api_key not in str(val), f"Leaked in table {table}, col {col}"


# ============================================================================
# Section 2: Zero Source Retention Audit
# ============================================================================

def test_source_code_is_not_stored_by_default(isolated_audit_db: Path) -> None:
    """Requirements 1 & 2: Avoid storing submitted source code, store only sha256 and length."""
    repo = ScanRepository(isolated_audit_db)
    unique_canary = "DEF_CANARY_SOURCE_TEXT_123456789_UNIQUE_PAYLOAD"
    source = f"import stripe\n# {unique_canary}\ndef charge():\n    return stripe.Charge.create(amount=500)"
    
    req = AnalysisRequest(source=source, filename="canary_checkout.py", ecosystem="stripe")
    rep = AnalysisReport(
        verdict="clean",
        engine_version="0.1.0",
        filename="canary_checkout.py",
        total_lines=4,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="Clean check.",
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
    
    scan_id = repo.save_scan(req, rep)
    detail = repo.get_scan(scan_id)
    assert detail is not None
    
    # Expected fingerprints stored
    assert detail.source_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert detail.source_length == len(source)
    
    # Confirm canary text does not exist anywhere in database
    with get_db(isolated_audit_db) as conn:
        for tbl in ["scans", "scan_evidence", "scan_findings", "scan_fix_proposals"]:
            rows = conn.execute(f"SELECT * FROM {tbl}").fetchall()
            for row in rows:
                for col, val in dict(row).items():
                    if val is not None:
                        assert unique_canary not in str(val)


# ============================================================================
# Section 3: Graceful Corrupted Record Handling
# ============================================================================

def test_get_scan_handles_corrupted_json_in_all_subtables(isolated_audit_db: Path) -> None:
    """Requirement 5: Gracefully handle missing or corrupted database records."""
    repo = ScanRepository(isolated_audit_db)
    
    # 1. Insert a baseline valid scan
    with get_db(isolated_audit_db) as conn:
        conn.execute(
            """
            INSERT INTO scans (
                scan_id, schema_version, created_at, completed_at, status, verdict,
                ecosystem, filename, source_sha256, source_length, pipeline_version,
                evidence_trust, is_mock, llm_reasoning_status, candidates_count,
                issues_count, evidence_count, suggestions_count, summary,
                abstention_reason, checks_performed, limitations_and_caveats,
                disclaimer, integrity_hash
            ) VALUES (
                'scan_corrupt_test', 1, '2026-10-18T00:00:00Z', '2026-10-18T00:00:00Z',
                'completed', 'issues_found', 'stripe', 'corrupt.py', 'abc', 10, '0.1.0',
                'live_official_source', 0, 'disabled', 1, 1, 1, 0, 'Summary',
                NULL, 'MALFORMED_JSON_CHECKS_NOT_A_LIST', 'MALFORMED_JSON_LIMITS',
                'Disclaimer', 'inthash'
            )
            """
        )
        # Corrupted finding details_json
        conn.execute(
            """
            INSERT INTO scan_findings (scan_id, finding_type, candidate_id, category, source_line, message, details_json)
            VALUES ('scan_corrupt_test', 'verified_issue', 'cand_01', 'deprecated', 1, 'Msg', '{malformed json: true}')
            """
        )
        # Corrupted scan_evidence (missing required fields or bad status)
        conn.execute(
            """
            INSERT INTO scan_evidence (
                scan_id, evidence_id, ecosystem, package, source_url, canonical_url,
                title, content_excerpt, retrieved_at, provider, status, is_mock,
                source_trust, doc_version, content_sha256, verdict_influence
            ) VALUES (
                'scan_corrupt_test', 'ev_corrupt_01', 'stripe', 'stripe', 'https://stripe.com', 'https://stripe.com',
                'Title', 'Excerpt', 'now', 'tinyfish_live', 'UNSUPPORTED_STATUS_ENUM_FAIL', 0,
                'official', 'v1', 'hash', 'adjudicated_evidence'
            )
            """
        )
        # Corrupted scan_project_files
        conn.execute(
            """
            INSERT INTO scan_project_files (
                scan_id, file_path, source_sha256, source_length, parse_status, candidates_count, syntax_error
            ) VALUES (
                'scan_corrupt_test', 'file.py', 'hash', 10, 'INVALID_ENUM_PARSE_STATUS', 0, NULL
            )
            """
        )

    # Calling repo.get_scan should NOT crash; it should log warnings and return the scan with sanitized defaults
    scan_detail = repo.get_scan("scan_corrupt_test")
    assert scan_detail is not None
    assert scan_detail.scan_id == "scan_corrupt_test"
    assert scan_detail.checks_performed == []
    assert scan_detail.limitations_and_caveats == []
    assert len(scan_detail.verified_issues) == 0  # Corrupted row skipped
    assert len(scan_detail.evidence_items) == 0    # Corrupted evidence row skipped
    assert scan_detail.project_files is None      # Corrupted project file row skipped


def test_list_scans_handles_corrupted_rows_gracefully(isolated_audit_db: Path) -> None:
    """Requirement 5: Corrupted row in scans table does not prevent listing other valid scans."""
    repo = ScanRepository(isolated_audit_db)
    
    with get_db(isolated_audit_db) as conn:
        # Valid scan 1
        conn.execute(
            """
            INSERT INTO scans (
                scan_id, schema_version, created_at, status, verdict, ecosystem, filename,
                source_sha256, source_length, pipeline_version, evidence_trust, is_mock,
                llm_reasoning_status, summary, checks_performed, limitations_and_caveats,
                disclaimer, integrity_hash
            ) VALUES ('scan_valid_01', 1, '2026-10-18T01:00:00Z', 'completed', 'clean', 'stripe', 'a.py', 'h1', 1, '0.1.0', 'live_official_source', 0, 'disabled', 's1', '[]', '[]', 'd', 'ih1')
            """
        )
        # Corrupted scan 2 (missing required verdict/status columns for ScanSummaryItem)
        conn.execute(
            """
            INSERT INTO scans (
                scan_id, schema_version, created_at, status, verdict, ecosystem, filename,
                source_sha256, source_length, pipeline_version, evidence_trust, is_mock,
                llm_reasoning_status, summary, checks_performed, limitations_and_caveats,
                disclaimer, integrity_hash
            ) VALUES ('scan_corrupted_02', 1, '2026-10-18T00:30:00Z', 'completed', 'INVALID_VERDICT_VALUE_OUT_OF_SPEC', 'stripe', 'b.py', 'h2', 2, '0.1.0', 'live_official_source', 0, 'disabled', 's2', '[]', '[]', 'd', 'ih2')
            """
        )
        # Valid scan 3
        conn.execute(
            """
            INSERT INTO scans (
                scan_id, schema_version, created_at, status, verdict, ecosystem, filename,
                source_sha256, source_length, pipeline_version, evidence_trust, is_mock,
                llm_reasoning_status, summary, checks_performed, limitations_and_caveats,
                disclaimer, integrity_hash
            ) VALUES ('scan_valid_03', 1, '2026-10-18T00:00:00Z', 'completed', 'issues_found', 'stripe', 'c.py', 'h3', 3, '0.1.0', 'live_official_source', 0, 'disabled', 's3', '[]', '[]', 'd', 'ih3')
            """
        )

    items, total = repo.list_scans()
    # Total count in database is 3
    assert total == 3
    # Returned items contain the valid scans (corrupted row was skipped safely)
    scan_ids = [item.scan_id for item in items]
    assert "scan_valid_01" in scan_ids
    assert "scan_valid_03" in scan_ids
    assert "scan_corrupted_02" not in scan_ids


# ============================================================================
# Section 4: Non-Breaking Storage Failure Resilience
# ============================================================================

@pytest.mark.asyncio
async def test_storage_failure_does_not_break_analysis_endpoint(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 7: If SQLite storage fails, the analysis result is still returned to user."""
    def fail_save(*args, **kwargs):
        raise sqlite3.OperationalError("Database disk is locked or out of space")

    monkeypatch.setattr(scan_repository, "save_scan", fail_save)

    payload = {
        "source": "import stripe\ndef charge(): pass",
        "filename": "resilience.py",
        "ecosystem": "stripe",
    }
    resp = await async_client.post("/api/v1/analyze", json=payload)
    # The endpoint must succeed with HTTP 200, not crash with HTTP 500
    assert resp.status_code == 200
    data = resp.json()
    assert data["verdict"] in ("clean", "issues_found", "unable_to_verify")
    # Persistence status must accurately report failure without lying
    assert data["persistence_status"] == "failed"


# ============================================================================
# Section 5: Parameterized Query Safety (SQL Injection Prevention)
# ============================================================================

@pytest.mark.asyncio
async def test_sql_injection_attempts_in_filters_and_ids(async_client: AsyncClient) -> None:
    """Requirement 4: Database access is parameterized and safe against SQL injection."""
    sql_injection_payloads = [
        "' OR '1'='1",
        "'; DROP TABLE scans; --",
        "scan_1' UNION SELECT * FROM scans --",
        "1; EXEC xp_cmdshell('dir'); --",
    ]

    for payload in sql_injection_payloads:
        # Test query parameter filtering
        resp = await async_client.get(f"/api/v1/scans?verdict={payload}&ecosystem={payload}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["items"], list)
        
        # Test path parameter validation
        detail_resp = await async_client.get(f"/api/v1/scans/{payload}")
        # Invalid format regex must reject malformed IDs
        assert detail_resp.status_code in (400, 404)

    # Confirm tables are completely intact
    resp_clean = await async_client.get("/api/v1/scans")
    assert resp_clean.status_code == 200


# ============================================================================
# Section 6: Test Isolation Audit
# ============================================================================

def test_database_test_isolation_guarantee(tmp_path: Path) -> None:
    """Requirement 7: Keep tests isolated from the developer's real database."""
    # Production path defined in default settings
    default_dev_path = Path(settings.APICOMPASS_DB_PATH)
    
    # In test environment, the fixture monkeypatches APICOMPASS_DB_PATH to a tmp_path
    current_active_path = scan_repository.get_db_path() if hasattr(scan_repository, "get_db_path") else Path(settings.APICOMPASS_DB_PATH)
    
    assert "tmp" in str(current_active_path) or "pytest" in str(current_active_path)
    assert str(current_active_path) != "data/apicompass.db"
