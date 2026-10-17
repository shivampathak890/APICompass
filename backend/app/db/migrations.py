"""Deterministic schema migration mechanism for SQLite audit repository."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple, Union
import sqlite3

from app.db.connection import get_db

logger = logging.getLogger("apicompass.db.migrations")

# Current maximum known schema migration version
CURRENT_SCHEMA_VERSION = 2

MIGRATION_V1_SQL = """
-- Migration 001: Initial audit history schema

CREATE TABLE IF NOT EXISTS scans (
    scan_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    verdict TEXT NOT NULL,
    ecosystem TEXT NOT NULL,
    filename TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_length INTEGER NOT NULL,
    pipeline_version TEXT NOT NULL,
    evidence_trust TEXT NOT NULL,
    is_mock INTEGER NOT NULL,
    llm_reasoning_status TEXT NOT NULL,
    candidates_count INTEGER NOT NULL DEFAULT 0,
    issues_count INTEGER NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    suggestions_count INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL,
    abstention_reason TEXT,
    checks_performed TEXT NOT NULL,
    limitations_and_caveats TEXT NOT NULL,
    disclaimer TEXT NOT NULL,
    integrity_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    ecosystem TEXT NOT NULL,
    package TEXT,
    source_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    content_excerpt TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    is_mock INTEGER NOT NULL,
    source_trust TEXT NOT NULL,
    doc_version TEXT,
    content_sha256 TEXT,
    verdict_influence TEXT
);

CREATE TABLE IF NOT EXISTS scan_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    finding_type TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    category TEXT NOT NULL,
    source_line INTEGER,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_fix_proposals (
    proposal_id TEXT PRIMARY KEY,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL,
    status TEXT NOT NULL,
    diff TEXT,
    syntax_valid INTEGER NOT NULL,
    reverification_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    explanation TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scans_created_at ON scans(created_at DESC, scan_id DESC);
CREATE INDEX IF NOT EXISTS idx_scans_verdict ON scans(verdict);
CREATE INDEX IF NOT EXISTS idx_scans_ecosystem ON scans(ecosystem);
CREATE INDEX IF NOT EXISTS idx_scans_source_sha256 ON scans(source_sha256);
CREATE INDEX IF NOT EXISTS idx_scan_evidence_scan_id ON scan_evidence(scan_id);
CREATE INDEX IF NOT EXISTS idx_scan_findings_scan_id ON scan_findings(scan_id);
CREATE INDEX IF NOT EXISTS idx_scan_fix_proposals_scan_id ON scan_fix_proposals(scan_id);
"""

MIGRATION_V2_SQL = """
-- Migration 002: Multi-file project audit metadata
CREATE TABLE IF NOT EXISTS scan_project_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_length INTEGER NOT NULL,
    parse_status TEXT NOT NULL,
    candidates_count INTEGER NOT NULL DEFAULT 0,
    syntax_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_scan_project_files_scan_id ON scan_project_files(scan_id);
"""

# Migration definitions: (version, name, sql_statement)
MIGRATIONS: List[Tuple[int, str, str]] = [
    (1, "initial_audit_schema", MIGRATION_V1_SQL),
    (2, "project_analysis_audit", MIGRATION_V2_SQL),
]


class MigrationError(Exception):
    """Raised when database schema migration fails."""
    pass


def get_applied_versions(conn: sqlite3.Connection) -> List[int]:
    """Retrieve list of already applied migration versions."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    cursor = conn.execute("SELECT version FROM schema_migrations ORDER BY version ASC")
    return [row["version"] for row in cursor.fetchall()]


def init_db(db_path_override: Optional[Union[str, Path]] = None) -> None:
    """Initialize database and apply pending migrations idempotently.

    Guarantees:
    - Never drops tables or erases existing history.
    - Applies migrations transactionally.
    - Rejects databases with future schema versions newer than CURRENT_SCHEMA_VERSION.
    """
    with get_db(db_path_override) as conn:
        applied = get_applied_versions(conn)

        # Check for unsupported future schema versions
        if applied and max(applied) > CURRENT_SCHEMA_VERSION:
            max_applied = max(applied)
            raise MigrationError(
                f"Database schema version {max_applied} is newer than supported engine version {CURRENT_SCHEMA_VERSION}. "
                "Please update APICompass to safely interact with this audit database."
            )

        # Apply pending migrations in order
        for version, name, sql in MIGRATIONS:
            if version not in applied:
                logger.info("Applying database migration %03d_%s", version, name)
                conn.executescript(sql)
                now_utc = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, now_utc),
                )
                logger.info("Successfully applied database migration %03d_%s", version, name)
