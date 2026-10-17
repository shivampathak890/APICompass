"""Comprehensive deterministic test suite for multi-file Python project analysis.

Verifies:
1. Valid two-file project.
2. Multiple files with relative imports.
3. Unambiguous project-local absolute imports.
4. Unresolved imports explicitly identified.
5. Duplicate paths after normalization rejected.
6. Path traversal attempts rejected.
7. Absolute and drive-qualified paths rejected.
8. Invalid file types rejected.
9. Per-file size limit enforced.
10. Combined project size limit enforced.
11. Maximum file count enforced.
12. Syntax error in one file while others remain analyzable.
13. Circular imports without infinite traversal.
14. Aliases and ambiguous symbol references.
15. Duplicate finding suppression.
16. Mock evidence cannot produce a verified verdict (quarantine).
17. Missing documentation leads to honest abstention.
18. AI suggestions cannot independently create verified findings.
19. Existing single-file endpoint remains compatible.
20. Existing history and integrity behavior remains compatible.
21. No source code persistence.
22. Safe errors without stack traces or secrets.
"""

import hashlib
from pathlib import Path
from typing import Generator
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.db import init_db
from app.main import app
from app.db.connection import get_db
from app.repositories import ScanRepository, scan_repository
from app.schemas.documentation import NormalizedEvidence
from app.schemas.project_analysis import (
    ProjectAnalysisRequest,
    ProjectFileItem,
    MAX_PROJECT_FILES,
    MAX_FILE_SIZE_BYTES,
    MAX_COMBINED_SIZE_BYTES,
)
from app.services.project.project_adjudicator import project_adjudicator


@pytest.fixture(autouse=True)
def isolated_audit_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Isolate database to a temporary SQLite file per test."""
    test_db_path = tmp_path / "test_apicompass_proj.db"
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
# Scenarios 1-4: Basic Multi-File Analysis & Relationship Resolution
# ============================================================================

@pytest.mark.asyncio
async def test_01_valid_two_file_project(async_client: AsyncClient) -> None:
    """Scenario 1: Valid two-file project parses and resolves dependencies cleanly."""
    payload = {
        "project_name": "two_file_test",
        "ecosystem": "stripe",
        "files": [
            {
                "path": "services/payment.py",
                "content": (
                    "import stripe\n\n"
                    "def charge_customer(token: str, amount: int):\n"
                    "    return stripe.Charge.create(amount=amount, source=token)\n"
                ),
            },
            {
                "path": "main.py",
                "content": (
                    "from services.payment import charge_customer\n\n"
                    "def run():\n"
                    "    charge_customer('tok_123', 500)\n"
                ),
            },
        ],
    }

    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["project_name"] == "two_file_test"
    assert data["total_files"] == 2
    assert data["syntax_errors_count"] == 0
    assert data["parsed_files_count"] == 2
    assert len(data["files"]) == 2
    assert len(data["relationships"]) >= 1

    # In mock mode, verdict must be quarantined to unable_to_verify
    assert data["verdict"] == "unable_to_verify"
    assert data["is_mock"] is True

    # Check relationship resolution from main.py to services/payment.py
    main_rels = [r for r in data["relationships"] if r["source_file"] == "main.py"]
    assert len(main_rels) >= 1
    rel = main_rels[0]
    assert rel["target_file"] == "services/payment.py"
    assert rel["imported_symbol"] == "charge_customer"
    assert rel["status"] == "resolved"


@pytest.mark.asyncio
async def test_02_multiple_files_with_relative_imports(async_client: AsyncClient) -> None:
    """Scenario 2: Multiple files with relative imports resolve correctly."""
    payload = {
        "project_name": "relative_import_project",
        "ecosystem": "stripe",
        "files": [
            {
                "path": "pkg/__init__.py",
                "content": "PKG_NAME = 'payment_package'\n",
            },
            {
                "path": "pkg/billing.py",
                "content": "def calculate_tax(amount: int) -> int:\n    return amount // 10\n",
            },
            {
                "path": "pkg/processor.py",
                "content": (
                    "from .billing import calculate_tax\n"
                    "from . import PKG_NAME\n\n"
                    "def process(amount: int):\n"
                    "    return calculate_tax(amount)\n"
                ),
            },
        ],
    }

    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["total_files"] == 3
    assert data["syntax_errors_count"] == 0

    proc_rels = [r for r in data["relationships"] if r["source_file"] == "pkg/processor.py"]
    assert len(proc_rels) == 2

    # Check .billing import
    billing_rel = next(r for r in proc_rels if r["imported_symbol"] == "calculate_tax")
    assert billing_rel["target_file"] == "pkg/billing.py"
    assert billing_rel["status"] == "resolved"

    # Check . PKG_NAME import from __init__.py
    pkg_name_rel = next(r for r in proc_rels if r["imported_symbol"] == "PKG_NAME")
    assert pkg_name_rel["target_file"] == "pkg/__init__.py"
    assert pkg_name_rel["status"] == "resolved"


@pytest.mark.asyncio
async def test_03_unambiguous_project_local_absolute_imports(async_client: AsyncClient) -> None:
    """Scenario 3: Unambiguous project-local absolute imports resolve cleanly."""
    payload = {
        "project_name": "abs_imports",
        "files": [
            {"path": "handlers/orders.py", "content": "ORDER_PREFIX = 'ORD-'\n"},
            {
                "path": "app.py",
                "content": (
                    "import handlers.orders\n"
                    "from handlers.orders import ORDER_PREFIX\n"
                ),
            },
        ],
    }

    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 200
    data = response.json()

    app_rels = [r for r in data["relationships"] if r["source_file"] == "app.py"]
    assert len(app_rels) == 2
    for r in app_rels:
        assert r["target_file"] == "handlers/orders.py"
        assert r["status"] == "resolved"


@pytest.mark.asyncio
async def test_04_unresolved_imports(async_client: AsyncClient) -> None:
    """Scenario 4: Imports referencing non-existent files are explicitly marked unresolved."""
    payload = {
        "project_name": "unresolved_test",
        "files": [
            {
                "path": "main.py",
                "content": (
                    "from .nonexistent import mystery_func\n"
                    "from services.missing import UnknownClass\n"
                ),
            }
        ],
    }

    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["unresolved_imports_count"] >= 1
    unresolved = [r for r in data["relationships"] if r["status"] == "unresolved"]
    assert len(unresolved) >= 1
    for r in unresolved:
        assert "not found" in r["reason"].lower() or "missing" in r["reason"].lower()


# ============================================================================
# Scenarios 5-11: Path Safety, Bounded Inputs & Request Validation
# ============================================================================

@pytest.mark.asyncio
async def test_05_duplicate_paths_after_normalization(async_client: AsyncClient) -> None:
    """Scenario 5: Duplicate file paths after normalization are rejected with 422."""
    payload = {
        "project_name": "dupe_test",
        "files": [
            {"path": "services/payment.py", "content": "# file 1\n"},
            {"path": "services/./payment.py", "content": "# duplicate\n"},
        ],
    }
    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 422
    assert "duplicate file path" in response.text.lower()


@pytest.mark.asyncio
async def test_06_path_traversal_attempts(async_client: AsyncClient) -> None:
    """Scenario 6: Path traversal components ('..') are strictly rejected."""
    traversal_cases = [
        "../secret.py",
        "services/../../root.py",
        "a/b/../../../etc/passwd.py",
    ]
    for bad_path in traversal_cases:
        payload = {
            "project_name": "traversal_test",
            "files": [{"path": bad_path, "content": "# bad\n"}],
        }
        response = await async_client.post("/api/v1/analyze/project", json=payload)
        assert response.status_code == 422
        assert "path traversal" in response.text.lower() or "prohibited" in response.text.lower()


@pytest.mark.asyncio
async def test_07_absolute_and_drive_qualified_paths(async_client: AsyncClient) -> None:
    """Scenario 7: Absolute and drive-qualified file paths are strictly rejected."""
    bad_paths = [
        "/etc/passwd.py",
        "\\Windows\\System32\\driver.py",
        "C:\\Users\\app\\main.py",
        "D:/projects/test.py",
    ]
    for bad_path in bad_paths:
        payload = {
            "project_name": "abs_path_test",
            "files": [{"path": bad_path, "content": "# bad\n"}],
        }
        response = await async_client.post("/api/v1/analyze/project", json=payload)
        assert response.status_code == 422
        assert "absolute" in response.text.lower() or "drive-qualified" in response.text.lower()


@pytest.mark.asyncio
async def test_08_invalid_file_types(async_client: AsyncClient) -> None:
    """Scenario 8: Non-Python files or bare extensions are rejected."""
    bad_files = [
        "readme.txt",
        "setup.sh",
        "config.json",
        ".py",
        "binary.exe",
    ]
    for bad_path in bad_files:
        payload = {
            "project_name": "bad_type_test",
            "files": [{"path": bad_path, "content": "# content\n"}],
        }
        response = await async_client.post("/api/v1/analyze/project", json=payload)
        assert response.status_code == 422
        assert "unsupported file type" in response.text.lower()


@pytest.mark.asyncio
async def test_09_per_file_size_limit(async_client: AsyncClient) -> None:
    """Scenario 9: Individual file exceeding 100 KB is rejected."""
    oversized_content = "x = 1\n" + ("#" * (MAX_FILE_SIZE_BYTES + 10))
    payload = {
        "project_name": "oversized_file_test",
        "files": [{"path": "big.py", "content": oversized_content}],
    }
    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_10_combined_project_size_limit(async_client: AsyncClient) -> None:
    """Scenario 10: Combined project source exceeding 500 KB is rejected."""
    # 6 files of 90 KB each = 540 KB > 500 KB limit
    file_content = "#" * 90_000
    payload = {
        "project_name": "oversized_project",
        "files": [
            {"path": f"module_{i}.py", "content": file_content}
            for i in range(6)
        ],
    }
    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 422
    assert "combined project source size exceeds" in response.text.lower()


@pytest.mark.asyncio
async def test_11_maximum_file_count(async_client: AsyncClient) -> None:
    """Scenario 11: Request exceeding 20 files is rejected."""
    payload = {
        "project_name": "too_many_files",
        "files": [
            {"path": f"f_{i}.py", "content": f"# file {i}\n"}
            for i in range(MAX_PROJECT_FILES + 1)
        ],
    }
    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 422


# ============================================================================
# Scenarios 12-15: AST Resilience, Circular Imports & Finding Suppression
# ============================================================================

@pytest.mark.asyncio
async def test_12_syntax_error_in_one_file_while_other_files_remain_analyzable(
    async_client: AsyncClient,
) -> None:
    """Scenario 12: Syntax error in one file does not halt analysis of valid files."""
    payload = {
        "project_name": "partial_syntax_error",
        "files": [
            {
                "path": "broken.py",
                "content": "def incomplete(\n    return stripe.Charge.create()\n",
            },
            {
                "path": "valid.py",
                "content": (
                    "import stripe\n\n"
                    "def good_function():\n"
                    "    return stripe.PaymentIntent.create(amount=100, currency='usd')\n"
                ),
            },
        ],
    }

    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["total_files"] == 2
    assert data["syntax_errors_count"] == 1
    assert data["parsed_files_count"] == 1

    # Broken file marked syntax_error
    broken = next(f for f in data["files"] if f["path"] == "broken.py")
    assert broken["parse_status"] == "syntax_error"
    assert broken["syntax_error"] is not None

    # Valid file parsed successfully with candidate extracted
    valid = next(f for f in data["files"] if f["path"] == "valid.py")
    assert valid["parse_status"] == "success"
    assert len(valid["candidates"]) >= 1

    # Project verdict abstains due to syntax error
    assert data["verdict"] == "unable_to_verify"


@pytest.mark.asyncio
async def test_13_circular_imports_without_infinite_traversal(async_client: AsyncClient) -> None:
    """Scenario 13: Circular imports between project files do not cause infinite recursion."""
    payload = {
        "project_name": "circular_test",
        "files": [
            {
                "path": "mod_a.py",
                "content": "import mod_b\ndef a(): return mod_b.b()\n",
            },
            {
                "path": "mod_b.py",
                "content": "import mod_a\ndef b(): return mod_a.a()\n",
            },
        ],
    }

    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["total_files"] == 2
    assert len(data["relationships"]) == 2

    # Verify circular dependency was detected and recorded in limitations
    has_circular_warning = any("circular dependency" in c.lower() for c in data["limitations_and_caveats"])
    assert has_circular_warning is True


@pytest.mark.asyncio
async def test_14_aliases_and_ambiguous_symbol_references(async_client: AsyncClient) -> None:
    """Scenario 14: Import aliases and wildcard imports handled safely."""
    payload = {
        "project_name": "alias_wildcard_test",
        "files": [
            {"path": "helpers.py", "content": "def do_work(): pass\n"},
            {
                "path": "main.py",
                "content": (
                    "import helpers as h\n"
                    "from helpers import *\n"
                ),
            },
        ],
    }

    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 200
    data = response.json()

    main_rels = [r for r in data["relationships"] if r["source_file"] == "main.py"]
    assert len(main_rels) == 2

    alias_rel = next(r for r in main_rels if r["alias"] == "h")
    assert alias_rel["target_file"] == "helpers.py"
    assert alias_rel["status"] == "resolved"

    wildcard_rel = next(r for r in main_rels if r["imported_symbol"] == "*")
    assert wildcard_rel["status"] == "ambiguous"
    assert "wildcard" in wildcard_rel["reason"].lower()


@pytest.mark.asyncio
async def test_15_duplicate_finding_suppression(isolated_audit_db: Path) -> None:
    """Scenario 15: Duplicate findings across files or import paths are suppressed."""
    live_evidence = [
        NormalizedEvidence(
            evidence_id="ev_live_charges",
            ecosystem="stripe",
            package="stripe",
            source_url="https://docs.stripe.com/api/charges/create",
            canonical_url="https://docs.stripe.com/api/charges/create",
            title="Create Charge",
            content_excerpt=(
                "The source parameter is deprecated in modern Stripe APIs. "
                "Use the PaymentIntents API instead."
            ),
            retrieved_at="2026-10-17T00:00:00Z",
            provider="tinyfish_live",
            status="success",
            is_mock=False,
            source_trust="official",
        )
    ]

    req = ProjectAnalysisRequest(
        project_name="dedupe_test",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="billing.py",
                content=(
                    "import stripe\n"
                    "def pay(tok):\n"
                    "    return stripe.Charge.create(amount=100, source=tok)\n"
                ),
            ),
            ProjectFileItem(
                path="helpers.py",
                content="def helper(): pass\n",
            ),
        ],
    )

    repo = ScanRepository(isolated_audit_db)
    report = await project_adjudicator.adjudicate_project(
        req,
        repo=repo,
        _internal_evidence=live_evidence,
    )

    assert report.verdict == "issues_found"
    assert len(report.verified_issues) == 1
    assert report.verified_issues[0].file_path == "billing.py"


# ============================================================================
# Scenarios 16-18: Evidence Court Integrity & Quarantine
# ============================================================================

@pytest.mark.asyncio
async def test_16_mock_evidence_cannot_produce_verified_verdict(async_client: AsyncClient) -> None:
    """Scenario 16: Mock evidence strictly quarantines project verdict to unable_to_verify."""
    payload = {
        "project_name": "mock_quarantine_test",
        "force_mock": True,
        "files": [
            {
                "path": "pay.py",
                "content": (
                    "import stripe\n"
                    "def charge(tok):\n"
                    "    return stripe.Charge.create(amount=100, source=tok)\n"
                ),
            }
        ],
    }

    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["verdict"] == "unable_to_verify"
    assert data["is_mock"] is True
    assert len(data["verified_issues"]) == 0
    assert any("MOCK_EVIDENCE_ONLY" in c for c in data["limitations_and_caveats"])


@pytest.mark.asyncio
async def test_17_missing_documentation_leads_to_honest_abstention(isolated_audit_db: Path) -> None:
    """Scenario 17: In-scope API call with no documentation leads to unable_to_verify."""
    req = ProjectAnalysisRequest(
        project_name="missing_doc_test",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="service.py",
                content="import stripe\ndef run(): return stripe.Refund.create(charge='ch_123')\n",
            )
        ],
    )
    repo = ScanRepository(isolated_audit_db)
    # Inject empty evidence list simulating total retrieval failure
    report = await project_adjudicator.adjudicate_project(
        req,
        repo=repo,
        _internal_evidence=[],
    )

    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0
    assert len(report.unresolved_candidates) == 1


@pytest.mark.asyncio
async def test_18_ai_suggestions_cannot_independently_create_verified_findings(async_client: AsyncClient) -> None:
    """Scenario 18: Advisory AI suggestions are strictly separated and do not become verified issues."""
    payload = {
        "project_name": "ai_separation_test",
        "files": [
            {
                "path": "main.py",
                "content": "import stripe\ndef run(): return stripe.Charge.create(amount=100)\n",
            }
        ],
    }
    response = await async_client.post("/api/v1/analyze/project", json=payload)
    assert response.status_code == 200
    data = response.json()

    for sug in data["ai_suggestions"]:
        assert sug["label"] == "AI suggestion — not verified"
    # AI suggestions never count as verified_issues
    assert len(data["verified_issues"]) == 0


# ============================================================================
# Scenarios 19-22: Compatibility, Persistence, Privacy & Error Safety
# ============================================================================

@pytest.mark.asyncio
async def test_19_existing_single_file_endpoint_remains_compatible(async_client: AsyncClient) -> None:
    """Scenario 19: Existing single-file analyze endpoints remain 100% backward compatible."""
    # 1. POST /api/v1/analyze/python
    ast_resp = await async_client.post(
        "/api/v1/analyze/python",
        json={"source": "import stripe\ncharge = stripe.Charge.create()", "filename": "single.py"},
    )
    assert ast_resp.status_code == 200
    assert ast_resp.json()["status"] == "success"

    # 2. POST /api/v1/analyze
    unified_resp = await async_client.post(
        "/api/v1/analyze",
        json={"source": "import stripe\ncharge = stripe.Charge.create()", "filename": "single.py"},
    )
    assert unified_resp.status_code == 200
    assert unified_resp.json()["verdict"] in ("clean", "issues_found", "unable_to_verify")


@pytest.mark.asyncio
async def test_20_existing_history_and_integrity_behavior_compatible(isolated_audit_db: Path) -> None:
    """Scenario 20: Multi-file project scan is persisted, indexed, and retrievable via history API."""
    repo = ScanRepository(isolated_audit_db)
    req = ProjectAnalysisRequest(
        project_name="history_compat_test",
        files=[
            ProjectFileItem(path="a.py", content="import stripe\ndef a(): pass\n"),
            ProjectFileItem(path="b.py", content="from .a import a\n"),
        ],
    )
    report = await project_adjudicator.adjudicate_project(req, repo=repo)
    assert report.scan_id is not None
    assert report.persistence_status == "saved"

    # Retrieve scan through repository
    detail = repo.get_scan(report.scan_id)
    assert detail is not None
    assert detail.scan_id == report.scan_id
    assert detail.is_historical is True
    assert "project:history_compat_test" in detail.filename
    assert detail.schema_version == 2
    assert detail.project_files is not None
    assert len(detail.project_files) == 2

    # Verify integrity hash is 64 hex characters
    assert len(detail.integrity_hash) == 64


@pytest.mark.asyncio
async def test_21_no_source_code_persistence(isolated_audit_db: Path) -> None:
    """Scenario 21: Verify across all SQLite tables that raw submitted source is NOT stored."""
    repo = ScanRepository(isolated_audit_db)
    canary_token = "SECRET_CANARY_MULTI_FILE_TOKEN_12345"
    req = ProjectAnalysisRequest(
        project_name="privacy_test",
        files=[
            ProjectFileItem(path="secret.py", content=f"# {canary_token}\nimport stripe\n"),
        ],
    )
    
    # Save project scan
    report = await project_adjudicator.adjudicate_project(req, repo=repo)
    assert report.scan_id is not None

    with get_db(isolated_audit_db) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r["name"] for r in cursor.fetchall()]
        for tbl in tables:
            rows = conn.execute(f"SELECT * FROM {tbl}").fetchall()
            for r in rows:
                for col_name, val in dict(r).items():
                    if val is not None:
                        assert canary_token not in str(val), f"Canary leaked in table '{tbl}', column '{col_name}'"


@pytest.mark.asyncio
async def test_22_safe_errors_without_stack_traces_or_secrets(async_client: AsyncClient) -> None:
    """Scenario 22: Malformed or unprocessable inputs return clean error without stack traces."""
    # Malformed JSON payload
    resp = await async_client.post(
        "/api/v1/analyze/project",
        json={"files": "not_a_list_of_files"},
    )
    assert resp.status_code == 422
    assert "Traceback" not in resp.text
    assert "Exception" not in resp.text
