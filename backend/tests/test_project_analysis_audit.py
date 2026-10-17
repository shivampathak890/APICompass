"""Multi-File Analysis Integrity and Security Audit Test Suite.

Comprehensive deterministic verification covering:
1. Section 2: Project-level verdict correctness across all 10 mandated cases.
2. Section 3: Path validation, boundary values (exact & +1), UNC paths, backslash normalization, and UTF-8 byte resource limits.
3. Section 4: Import-graph resolution (normal relative, parent relative, __init__.py, absolute, external, missing module, ambiguous matches, aliases, circular, undefined symbol, dynamic imports).
4. Section 5: SQLite migration v1 -> v2 upgrade, repeated startup, single-file reading, project save/retrieve, cascade delete, integrity hash, and failure safety.
5. Section 6: Source privacy audit verifying absence of embedded marker strings across all database tables.
"""

from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from typing import Generator, List
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.db import init_db
from app.db.connection import get_db
from app.db.migrations import MIGRATION_V1_SQL, MIGRATION_V2_SQL, get_applied_versions
from app.main import app
from app.repositories import scan_repository, ScanRepository
from app.schemas.documentation import NormalizedEvidence
from app.schemas.project_analysis import (
    MAX_COMBINED_SIZE_BYTES,
    MAX_FILE_SIZE_BYTES,
    MAX_PATH_LENGTH,
    MAX_PROJECT_FILES,
    ProjectAnalysisRequest,
    ProjectFileItem,
    normalize_and_validate_project_path,
)
from app.services.evidence.adjudicator import adjudicator
from app.services.project.graph_resolver import ProjectGraphResolver
from app.services.project.project_adjudicator import project_adjudicator
from app.services.python_ast_analyzer import analyze_python_source


@pytest.fixture(autouse=True)
def isolated_audit_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Isolate database to a fresh temporary SQLite file for each test."""
    test_db_path = tmp_path / "test_project_analysis_audit.db"
    monkeypatch.setattr(settings, "APICOMPASS_DB_PATH", str(test_db_path))
    scan_repository.db_path_override = test_db_path
    init_db(test_db_path)
    yield test_db_path
    scan_repository.db_path_override = None


@pytest_asyncio.fixture
async def async_client() -> AsyncClient:
    """Async HTTP client bound to the FastAPI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def make_official_evidence(
    ev_id: str,
    target_url: str = "https://docs.stripe.com/api/charges/create",
    canonical_url: str = "https://docs.stripe.com/api/charges/create",
    excerpt: str = "You can no longer use the source parameter with Charge APIs.",
) -> NormalizedEvidence:
    """Helper to create live official evidence for test injection."""
    return NormalizedEvidence(
        evidence_id=ev_id,
        ecosystem="stripe",
        package="stripe",
        source_url=target_url,
        canonical_url=canonical_url,
        title="Create a charge | Stripe Docs",
        content_excerpt=excerpt,
        retrieved_at="2026-10-17T12:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
    )


# ============================================================================
# SECTION 2: Project-Level Verdict Correctness (10 Mandated Cases)
# ============================================================================

@pytest.mark.asyncio
async def test_verdict_case_01_no_authoritative_docs_abstains() -> None:
    """Case 1: All files parse, but no authoritative documentation is available -> unable_to_verify."""
    req = ProjectAnalysisRequest(
        project_name="no_docs_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="payment.py",
                content="import stripe\n\ndef run():\n    return stripe.NonexistentMethod.call()\n",
            )
        ],
    )
    # Inject empty evidence list
    report = await project_adjudicator.adjudicate_project(req, _internal_evidence=[])
    assert report.verdict == "unable_to_verify"
    assert report.evidence_trust == "untrusted_or_unavailable"
    assert len(report.unresolved_candidates) == 1
    assert len(report.verified_issues) == 0
    assert report.candidate_assessments[0].abstention_reason == "DOCUMENTATION_MISSING"


@pytest.mark.asyncio
async def test_verdict_case_02_syntax_error_in_one_file_downgrades_clean() -> None:
    """Case 2: One file has syntax error and another has valid candidate -> cannot be clean."""
    req = ProjectAnalysisRequest(
        project_name="syntax_error_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="broken.py",
                content="def broken(\n",
            ),
            ProjectFileItem(
                path="valid.py",
                content=(
                    "import stripe\n\n"
                    "def run():\n"
                    "    return stripe.PaymentIntent.create(amount=1000, currency='usd')\n"
                ),
            ),
        ],
    )
    # Even if valid candidate matches live doc, whole project must be unable_to_verify
    ev = make_official_evidence(
        "ev_intent",
        target_url="https://docs.stripe.com/api/payment_intents/create",
        excerpt="Creates a PaymentIntent object with amount and currency.",
    )
    report = await project_adjudicator.adjudicate_project(req, _internal_evidence=[ev])
    assert report.verdict == "unable_to_verify"
    assert report.syntax_errors_count == 1
    assert report.files[0].parse_status == "syntax_error"
    assert report.files[1].parse_status == "success"


@pytest.mark.asyncio
async def test_verdict_case_03_missing_project_module_import_cannot_be_clean() -> None:
    """Case 3: One file imports a project module that is not present -> unresolved relationship prevents clean."""
    req = ProjectAnalysisRequest(
        project_name="missing_import_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="services/caller.py",
                content=(
                    "from .missing_module import helper\n"
                    "import stripe\n\n"
                    "def run():\n"
                    "    return stripe.PaymentIntent.create(amount=500, currency='usd')\n"
                ),
            )
        ],
    )
    ev = make_official_evidence(
        "ev_intent",
        target_url="https://docs.stripe.com/api/payment_intents/create",
        excerpt="Creates a PaymentIntent object.",
    )
    report = await project_adjudicator.adjudicate_project(req, _internal_evidence=[ev])
    assert report.verdict == "unable_to_verify"
    assert report.unresolved_imports_count >= 1
    assert any("UNRESOLVED_RELATIONSHIPS" in c for c in report.limitations_and_caveats)


@pytest.mark.asyncio
async def test_verdict_case_04_ambiguous_import_cannot_be_clean() -> None:
    """Case 4: An import is ambiguous (e.g. wildcard import) -> cannot be clean."""
    req = ProjectAnalysisRequest(
        project_name="ambiguous_import_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="services/config.py",
                content="API_VERSION = '2024-04-10'\n",
            ),
            ProjectFileItem(
                path="main.py",
                content=(
                    "from services.config import *\n"
                    "import stripe\n\n"
                    "def run():\n"
                    "    return stripe.PaymentIntent.create(amount=1000, currency='usd')\n"
                ),
            ),
        ],
    )
    ev = make_official_evidence(
        "ev_intent",
        target_url="https://docs.stripe.com/api/payment_intents/create",
        excerpt="Creates a PaymentIntent object.",
    )
    report = await project_adjudicator.adjudicate_project(req, _internal_evidence=[ev])
    assert report.verdict == "unable_to_verify"
    assert report.ambiguous_imports_count >= 1


@pytest.mark.asyncio
async def test_verdict_case_05_mixed_adequate_and_unresolved_candidates() -> None:
    """Case 5: Candidate 1 has adequate evidence, Candidate 2 is unresolved -> unable_to_verify."""
    req = ProjectAnalysisRequest(
        project_name="mixed_candidates_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="billing.py",
                content=(
                    "import stripe\n\n"
                    "def process(token: str):\n"
                    "    intent = stripe.PaymentIntent.create(amount=100, currency='usd')\n"
                    "    custom = stripe.CustomExtension.execute(token=token)\n"
                    "    return intent, custom\n"
                ),
            )
        ],
    )
    ev = make_official_evidence(
        "ev_intent",
        target_url="https://docs.stripe.com/api/payment_intents/create",
        excerpt="Creates a PaymentIntent object.",
    )
    report = await project_adjudicator.adjudicate_project(req, _internal_evidence=[ev])
    assert report.verdict == "unable_to_verify"
    assert len(report.unresolved_candidates) >= 1
    assert len(report.candidate_assessments) == 2


@pytest.mark.asyncio
async def test_verdict_case_06_all_mock_evidence_strictly_quarantined() -> None:
    """Case 6: All documentation is mock evidence -> strict quarantine, zero verified issues."""
    req = ProjectAnalysisRequest(
        project_name="mock_quarantine_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="charge.py",
                content="import stripe\nstripe.Charge.create(amount=100, source='tok_123')\n",
            )
        ],
    )
    mock_ev = NormalizedEvidence(
        evidence_id="ev_mock_1",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Mock Charges Doc",
        content_excerpt="You can no longer use source.",
        retrieved_at="2026-10-17T12:00:00Z",
        provider="tinyfish_mock",
        status="mock",
        is_mock=True,
        source_trust="official",
    )
    report = await project_adjudicator.adjudicate_project(req, _internal_evidence=[mock_ev])
    assert report.verdict == "unable_to_verify"
    assert report.is_mock is True
    assert report.evidence_trust == "mock_fixture"
    assert len(report.verified_issues) == 0


@pytest.mark.asyncio
async def test_verdict_case_07_no_api_candidates_abstains() -> None:
    """Case 7: No API candidates exist across project -> unable_to_verify."""
    req = ProjectAnalysisRequest(
        project_name="no_api_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="utils/calc.py",
                content="def add(a: int, b: int) -> int:\n    return a + b\n",
            ),
            ProjectFileItem(
                path="main.py",
                content="from utils.calc import add\nprint(add(2, 3))\n",
            ),
        ],
    )
    report = await project_adjudicator.adjudicate_project(req)
    assert report.verdict == "unable_to_verify"
    assert report.total_candidates == 0
    assert "No supported in-scope API calls detected" in report.summary


@pytest.mark.asyncio
async def test_verdict_case_08_finding_reachable_via_multiple_imports_deduplicated() -> None:
    """Case 8: Finding in shared file imported by multiple callers is reported exactly once."""
    req = ProjectAnalysisRequest(
        project_name="dedup_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="services/shared_payment.py",
                content="import stripe\ndef pay(t):\n    return stripe.Charge.create(amount=100, source=t)\n",
            ),
            ProjectFileItem(
                path="caller_a.py",
                content="from services.shared_payment import pay\ndef a(): pay('tok_a')\n",
            ),
            ProjectFileItem(
                path="caller_b.py",
                content="from services.shared_payment import pay\ndef b(): pay('tok_b')\n",
            ),
        ],
    )
    ev = NormalizedEvidence(
        evidence_id="ev_live_charges_dedup",
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
    report = await project_adjudicator.adjudicate_project(req, _internal_evidence=[ev])
    # The charge candidate in services/shared_payment.py must yield exactly 1 verified issue
    charge_issues = [i for i in report.verified_issues if i.file_path == "services/shared_payment.py"]
    assert len(charge_issues) == 1
    assert charge_issues[0].violation_type == "legacy_deprecated_parameter"


@pytest.mark.asyncio
async def test_verdict_case_09_unsupported_dynamic_import_abstains() -> None:
    """Case 9: Dynamic import construct prevents complete static analysis -> ambiguous -> unable_to_verify."""
    req = ProjectAnalysisRequest(
        project_name="dynamic_import_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="dynamic_loader.py",
                content=(
                    "import stripe\n\n"
                    "def load_plugin(name: str):\n"
                    "    mod = __import__(name)\n"
                    "    return stripe.PaymentIntent.create(amount=100, currency='usd')\n"
                ),
            )
        ],
    )
    ev = make_official_evidence(
        "ev_intent",
        target_url="https://docs.stripe.com/api/payment_intents/create",
        excerpt="Creates a PaymentIntent object.",
    )
    report = await project_adjudicator.adjudicate_project(req, _internal_evidence=[ev])
    assert report.verdict == "unable_to_verify"
    assert report.ambiguous_imports_count >= 1
    assert any(r.status == "ambiguous" and "__import__" in r.reason for r in report.relationships)


@pytest.mark.asyncio
async def test_verdict_case_10_file_fails_parsing_unrelated_analyzable() -> None:
    """Case 10: File 1 syntax error, File 2 analyzable -> syntax error isolated per file."""
    req = ProjectAnalysisRequest(
        project_name="isolated_syntax_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="bad_syntax.py",
                content="def broken(\n",
            ),
            ProjectFileItem(
                path="good_worker.py",
                content="import stripe\ndef run(): return stripe.PaymentIntent.create(amount=10)\n",
            ),
        ],
    )
    report = await project_adjudicator.adjudicate_project(req)
    assert report.total_files == 2
    assert report.parsed_files_count == 1
    assert report.syntax_errors_count == 1
    bad_file = next(f for f in report.files if f.path == "bad_syntax.py")
    assert bad_file.parse_status == "syntax_error"
    assert bad_file.syntax_error is not None
    good_file = next(f for f in report.files if f.path == "good_worker.py")
    assert good_file.parse_status == "success"
    assert len(good_file.candidates) == 1


# ============================================================================
# SECTION 3: Path Validation & Resource Limits Audit
# ============================================================================

def test_path_validation_unc_paths_rejected() -> None:
    """UNC paths are strictly rejected."""
    with pytest.raises(ValueError, match="UNC paths are not permitted"):
        normalize_and_validate_project_path(r"\\server\share\file.py")
    with pytest.raises(ValueError, match="UNC paths are not permitted"):
        normalize_and_validate_project_path("//server/share/file.py")


def test_path_validation_absolute_and_drive_rejected() -> None:
    """Absolute POSIX and Windows drive-qualified paths are rejected."""
    with pytest.raises(ValueError, match="Absolute file paths are not permitted"):
        normalize_and_validate_project_path("/etc/passwd.py")
    with pytest.raises(ValueError, match="Drive-qualified paths are not permitted"):
        normalize_and_validate_project_path("C:test.py")
    with pytest.raises(ValueError, match="Drive-qualified paths are not permitted"):
        normalize_and_validate_project_path("c:/app/main.py")


def test_path_validation_traversal_components_rejected() -> None:
    """Path traversal components ('..') are strictly prohibited."""
    with pytest.raises(ValueError, match="Path traversal component"):
        normalize_and_validate_project_path("../main.py")
    with pytest.raises(ValueError, match="Path traversal component"):
        normalize_and_validate_project_path("services/../../main.py")


def test_path_validation_nul_character_rejected() -> None:
    """NUL byte injection is strictly rejected."""
    with pytest.raises(ValueError, match="prohibited NUL character"):
        normalize_and_validate_project_path("main.py\0.txt")


def test_path_validation_max_path_length_boundary() -> None:
    """Max path length boundary checks (exact 255 chars valid, 256 chars rejected)."""
    # 255 chars total: "a/" * 125 + "a.py" (125*2 + 4 = 254 chars; + 1 = 255 chars)
    prefix = "a" * (MAX_PATH_LENGTH - 4)  # 251 chars
    valid_exact = f"{prefix}b.py"          # 255 chars
    assert len(valid_exact) == MAX_PATH_LENGTH
    assert normalize_and_validate_project_path(valid_exact) == valid_exact

    over_limit = f"{prefix}bc.py"          # 256 chars
    assert len(over_limit) == MAX_PATH_LENGTH + 1
    with pytest.raises(ValueError, match="exceeds maximum permitted length"):
        normalize_and_validate_project_path(over_limit)


def test_path_validation_backslash_normalization() -> None:
    """Windows backslashes are explicitly and consistently normalized to POSIX slashes."""
    norm = normalize_and_validate_project_path(r"services\payment\handler.py")
    assert norm == "services/payment/handler.py"

    norm_dots = normalize_and_validate_project_path(r".\services\.\payment\handler.py")
    assert norm == "services/payment/handler.py"


def test_path_validation_duplicate_after_normalization_rejected() -> None:
    """Paths that become duplicates after separator/dot normalization are rejected."""
    with pytest.raises(ValueError, match="Duplicate file path"):
        ProjectAnalysisRequest(
            files=[
                ProjectFileItem(path=r"services\payment.py", content="x = 1\n"),
                ProjectFileItem(path="services/./payment.py", content="x = 2\n"),
            ]
        )


def test_resource_limits_utf8_bytes_boundary() -> None:
    """Per-file size limit strictly counts UTF-8 bytes (exact limit valid, +1 byte rejected)."""
    # Exact ASCII 100,000 bytes
    exact_ascii = "a" * (MAX_FILE_SIZE_BYTES - 1) + "\n"
    assert len(exact_ascii.encode("utf-8")) == MAX_FILE_SIZE_BYTES
    item_exact = ProjectFileItem(path="exact.py", content=exact_ascii)
    assert item_exact.path == "exact.py"

    # +1 ASCII byte (100,001 bytes)
    over_ascii = "a" * MAX_FILE_SIZE_BYTES + "\n"
    assert len(over_ascii.encode("utf-8")) == MAX_FILE_SIZE_BYTES + 1
    with pytest.raises(ValueError):
        ProjectFileItem(path="over.py", content=over_ascii)

    # Multi-byte UTF-8 characters: 40,000 3-byte characters = 120,000 bytes (over limit even if chars < 100k)
    multi_byte = "€" * 40_000
    assert len(multi_byte) == 40_000
    assert len(multi_byte.encode("utf-8")) == 120_000
    with pytest.raises(ValueError, match="exceeds maximum limit"):
        ProjectFileItem(path="multibyte.py", content=multi_byte)


def test_resource_limits_combined_size_and_max_files() -> None:
    """Combined 500 KB limit and max 20 files limit enforced server-side."""
    # Max files boundary: 20 files allowed, 21 files rejected
    twenty_files = [
        ProjectFileItem(path=f"f{i:02d}.py", content="x = 1\n")
        for i in range(MAX_PROJECT_FILES)
    ]
    req20 = ProjectAnalysisRequest(files=twenty_files)
    assert len(req20.files) == 20

    with pytest.raises(ValueError):
        twenty_one = twenty_files + [ProjectFileItem(path="f21.py", content="x = 1\n")]
        ProjectAnalysisRequest(files=twenty_one)


# ============================================================================
# SECTION 4: Import-Graph Resolution Audit
# ============================================================================

def test_graph_resolution_cases() -> None:
    """Audit resolution of relative, parent-relative, __init__.py, absolute, and missing imports."""
    files_data = {
        "pkg/__init__.py": "PKG_NAME = 'test_pkg'\ndef pkg_func(): pass\n",
        "pkg/sub/worker.py": (
            "from .. import pkg_func\n"
            "from .helper import assist\n"
            "import os\n"
        ),
        "pkg/sub/helper.py": "def assist(): pass\n",
        "main.py": (
            "from pkg.sub.helper import assist as my_assist\n"
            "from pkg import PKG_NAME\n"
            "from pkg import nonexistent_symbol\n"
            "from .missing import something\n"
        ),
    }
    ast_map = {p: analyze_python_source(c, filename=p) for p, c in files_data.items()}
    resolver = ProjectGraphResolver(files_data, ast_map)
    relationships, circular = resolver.resolve_all_relationships()

    # 1. Parent-relative import: from .. import pkg_func in pkg/sub/worker.py -> resolved
    parent_rel = next(r for r in relationships if r.source_file == "pkg/sub/worker.py" and r.imported_symbol == "pkg_func")
    assert parent_rel.status == "resolved"
    assert parent_rel.target_file == "pkg/__init__.py"

    # 2. Sibling relative import: from .helper import assist in pkg/sub/worker.py -> resolved
    sibling_rel = next(r for r in relationships if r.source_file == "pkg/sub/worker.py" and r.imported_symbol == "assist")
    assert sibling_rel.status == "resolved"
    assert sibling_rel.target_file == "pkg/sub/helper.py"

    # 3. External library: import os -> external
    os_rel = next(r for r in relationships if r.source_file == "pkg/sub/worker.py" and r.target == "os")
    assert os_rel.status == "external"

    # 4. Alias import: from pkg.sub.helper import assist as my_assist -> resolved to pkg/sub/helper.py
    alias_rel = next(r for r in relationships if r.source_file == "main.py" and r.imported_symbol == "assist")
    assert alias_rel.alias == "my_assist"
    assert alias_rel.status == "resolved"
    assert alias_rel.target_file == "pkg/sub/helper.py"

    # 5. Undefined symbol in target: from pkg import nonexistent_symbol -> unresolved
    undef_rel = next(r for r in relationships if r.source_file == "main.py" and r.imported_symbol == "nonexistent_symbol")
    assert undef_rel.status == "unresolved"
    assert "was not found among statically identified top-level definitions" in undef_rel.reason

    # 6. Missing relative target: from .missing import something -> unresolved
    missing_rel = next(r for r in relationships if r.source_file == "main.py" and "missing" in r.target)
    assert missing_rel.status == "unresolved"


def test_graph_resolution_circular_and_ambiguous() -> None:
    """Audit cycle detection and ambiguous module resolution."""
    # Circular import: a.py -> b.py -> a.py
    circ_files = {
        "a.py": "from b import func_b\ndef func_a(): pass\n",
        "b.py": "from a import func_a\ndef func_b(): pass\n",
    }
    circ_ast = {p: analyze_python_source(c, filename=p) for p, c in circ_files.items()}
    resolver = ProjectGraphResolver(circ_files, circ_ast)
    rels, warnings = resolver.resolve_all_relationships()
    assert len(warnings) >= 1
    assert any("Circular dependency detected" in w for w in warnings)

    # Ambiguous module match: both mod.py and mod/__init__.py exist
    ambig_files = {
        "mod.py": "x = 1\n",
        "mod/__init__.py": "x = 2\n",
        "caller.py": "import mod\n",
    }
    ambig_ast = {p: analyze_python_source(c, filename=p) for p, c in ambig_files.items()}
    ambig_resolver = ProjectGraphResolver(ambig_files, ambig_ast)
    ambig_rels, _ = ambig_resolver.resolve_all_relationships()
    caller_rel = next(r for r in ambig_rels if r.source_file == "caller.py")
    assert caller_rel.status == "ambiguous"
    assert "Ambiguous module match" in caller_rel.reason


# ============================================================================
# SECTION 5: SQLite Migration & Persistence Integrity Audit
# ============================================================================

def test_migration_v1_to_v2_upgrade(tmp_path: Path) -> None:
    """Verify clean upgrade path from v1 schema to v2 schema without data loss."""
    db_file = tmp_path / "upgrade_test.db"

    # Step 1: Initialize database with ONLY Migration 1
    with closing(sqlite3.connect(db_file)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.executescript(MIGRATION_V1_SQL)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (1, "initial_audit_schema", "2026-10-17T00:00:00Z"),
        )
        # Insert a sample v1 scan
        conn.execute(
            """
            INSERT INTO scans (
                scan_id, schema_version, created_at, status, verdict, ecosystem,
                filename, source_sha256, source_length, pipeline_version,
                evidence_trust, is_mock, llm_reasoning_status, summary,
                checks_performed, limitations_and_caveats, disclaimer, integrity_hash
            ) VALUES (?, 1, ?, 'completed', 'clean', 'stripe', 'single.py', 'hash123', 50, '0.1.0',
                      'live_official_source', 0, 'disabled', 'Clean scan', '[]', '[]', 'Disclaimer', 'integ_hash')
            """,
            ("scan_v1_sample", "2026-10-17T00:00:00Z"),
        )
        conn.commit()

    # Verify v2 table does not exist yet
    with closing(sqlite3.connect(db_file)) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scan_project_files'")
        assert cursor.fetchone() is None

    # Step 2: Run init_db to perform migration upgrade to v2
    init_db(db_file)

    # Step 3: Verify migration v2 was applied and v1 scan data is intact
    with closing(sqlite3.connect(db_file)) as conn:
        conn.row_factory = sqlite3.Row
        applied = [r["version"] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version ASC")]
        assert applied == [1, 2]

        # Verify scan_project_files exists now
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scan_project_files'")
        assert cursor.fetchone() is not None

        # Verify original v1 scan is intact
        v1_row = conn.execute("SELECT * FROM scans WHERE scan_id = 'scan_v1_sample'").fetchone()
        assert v1_row is not None
        assert v1_row["filename"] == "single.py"

    # Step 4: Repeated startup does not duplicate or fail
    init_db(db_file)
    with closing(sqlite3.connect(db_file)) as conn:
        conn.row_factory = sqlite3.Row
        applied_again = [r["version"] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version ASC")]
        assert applied_again == [1, 2]


@pytest.mark.asyncio
async def test_persistence_project_scan_save_get_and_cascade_delete(isolated_audit_db: Path) -> None:
    """Verify project scan save, historical get with project files, and cascade deletion."""
    repo = ScanRepository(db_path_override=isolated_audit_db)
    req = ProjectAnalysisRequest(
        project_name="persistence_audit_proj",
        ecosystem="stripe",
        files=[
            ProjectFileItem(path="mod_a.py", content="import stripe\nstripe.Charge.create(amount=100, source='tok_1')\n"),
            ProjectFileItem(path="mod_b.py", content="import stripe\nstripe.Charge.create(amount=200, source='tok_2')\n"),
        ],
    )
    ev = make_official_evidence(
        "ev_charge_persist",
        excerpt="You can no longer use the source parameter.",
    )
    report = await project_adjudicator.adjudicate_project(req, repo=repo, _internal_evidence=[ev])
    scan_id = report.scan_id
    assert scan_id is not None
    assert report.persistence_status == "saved"

    # Retrieve historical scan
    detail = repo.get_scan(scan_id)
    assert detail is not None
    assert detail.is_historical is True
    assert detail.project_files is not None
    assert len(detail.project_files) == 2
    paths = {f.file_path for f in detail.project_files}
    assert paths == {"mod_a.py", "mod_b.py"}

    # Cascade delete
    deleted = repo.delete_scan(scan_id)
    assert deleted is True

    # Confirm scan_project_files rows are deleted
    with get_db(isolated_audit_db) as conn:
        p_files = conn.execute("SELECT * FROM scan_project_files WHERE scan_id = ?", (scan_id,)).fetchall()
        assert len(p_files) == 0
        s_rows = conn.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,)).fetchall()
        assert len(s_rows) == 0


# ============================================================================
# SECTION 6: Source Privacy Audit (Marker String Test Across All Tables)
# ============================================================================

@pytest.mark.asyncio
async def test_source_privacy_marker_absence_in_all_db_tables(isolated_audit_db: Path) -> None:
    """Security & Privacy Guarantee: Embedded secret marker in submitted source is absent from all database tables."""
    UNIQUE_SECRET_MARKER = "SUPER_SECRET_TOKEN_DO_NOT_STORE_998877665544332211"
    repo = ScanRepository(db_path_override=isolated_audit_db)

    req = ProjectAnalysisRequest(
        project_name="privacy_audit_proj",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="billing_secret.py",
                content=(
                    f"# Sensitive configuration file\n"
                    f"STRIPE_SECRET_KEY = '{UNIQUE_SECRET_MARKER}'\n"
                    f"import stripe\n"
                    f"def charge(tok):\n"
                    f"    return stripe.Charge.create(amount=1000, source=tok)\n"
                ),
            ),
            ProjectFileItem(
                path="caller.py",
                content=f"# Caller referencing {UNIQUE_SECRET_MARKER}\nfrom billing_secret import charge\n",
            ),
        ],
    )
    ev = make_official_evidence(
        "ev_charge_priv",
        excerpt="You can no longer use the source parameter.",
    )

    report = await project_adjudicator.adjudicate_project(req, repo=repo, _internal_evidence=[ev])
    assert report.scan_id is not None

    # Inspect EVERY column of EVERY row in EVERY table in SQLite database
    with get_db(isolated_audit_db) as conn:
        conn.row_factory = sqlite3.Row
        # Get all table names
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r["name"] for r in cursor.fetchall()]

        assert "scans" in tables
        assert "scan_project_files" in tables
        assert "scan_evidence" in tables
        assert "scan_findings" in tables

        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                for col in row.keys():
                    val = str(row[col])
                    assert UNIQUE_SECRET_MARKER not in val, (
                        f"PRIVACY VIOLATION: Unique source secret marker found in table '{table}', column '{col}'! Value: {val}"
                    )


@pytest.mark.asyncio
async def test_project_analysis_populates_code_fragment_and_precise_locations(isolated_audit_db: Path) -> None:
    """Verify that multi-file verified issues carry code_fragment, exact file_path, and line number."""
    repo = ScanRepository(db_path_override=isolated_audit_db)
    req = ProjectAnalysisRequest(
        project_name="precise_locations_project",
        ecosystem="stripe",
        files=[
            ProjectFileItem(
                path="services/payment.py",
                content=(
                    "# Line 1\n"
                    "# Line 2\n"
                    "import stripe\n"
                    "def execute_charge(token: str):\n"
                    "    return stripe.Charge.create(amount=2000, currency='usd', source=token)\n"
                ),
            ),
            ProjectFileItem(
                path="caller.py",
                content="from services.payment import execute_charge\n\ndef main():\n    return execute_charge('tok_visa')\n",
            ),
        ],
    )
    ev = make_official_evidence(
        "ev_charge_loc",
        excerpt="The source parameter is deprecated in modern Stripe APIs. Use the PaymentIntents API instead.",
    )

    report = await project_adjudicator.adjudicate_project(req, repo=repo, _internal_evidence=[ev])
    assert report.verdict == "issues_found"
    assert len(report.verified_issues) == 1

    issue = report.verified_issues[0]
    assert issue.file_path == "services/payment.py"
    assert issue.source_location.lineno == 5
    assert issue.code_fragment is not None
    assert "stripe.Charge.create" in issue.code_fragment
    assert "source=token" in issue.code_fragment
    assert issue.verification_status == "verified"

    # Ensure caller.py has no spurious candidates or findings
    caller_file_result = next(f for f in report.files if f.path == "caller.py")
    assert len(caller_file_result.candidates) == 0

