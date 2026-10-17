"""SQLite audit repository for storing and retrieving scan history and evidence provenance."""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

from app.db.connection import get_db
from app.schemas.evidence import (
    AnalysisRequest,
    AnalysisReport,
    VerifiedIssue,
    AISuggestion,
)
from app.schemas.documentation import NormalizedEvidence
from app.schemas.scan_history import ScanSummaryItem, HistoricalScanDetail, ProjectFileDetailSummary
from app.schemas.fix_proposal import FixProposalResponse
from app.schemas.project_analysis import ProjectAnalysisRequest, ProjectAnalysisReport
from app.services.llm.secret_scrubber import scrub_secrets

logger = logging.getLogger("apicompass.repositories.scan_repository")


def compute_record_integrity_hash(
    scan_id: str,
    created_at: str,
    verdict: str,
    ecosystem: str,
    filename: str,
    source_sha256: str,
    source_length: int,
    evidence_trust: str,
    is_mock: bool,
    verified_issues: List[Any],
    evidence_items: List[Any],
    checks_performed: List[str],
    summary: str,
) -> str:
    """Compute deterministic SHA-256 integrity hash over canonical scan attributes.

    Covers:
    - scan identification & timestamp (scan_id, created_at)
    - adjudication outcome (verdict, summary)
    - source code fingerprint (source_sha256, source_length, filename, ecosystem)
    - evidence & trust state (evidence_trust, is_mock)
    - deterministic verified findings & quote receipts
    - canonical evidence provenance IDs & URLs
    - checks performed
    """
    canonical_issues = [
        {
            "candidate_id": getattr(i, "candidate_id", ""),
            "violation_type": getattr(i, "violation_type", ""),
            "line": getattr(getattr(i, "source_location", None), "lineno", None),
            "quote_hash": getattr(getattr(i, "quote_verification", None), "content_hash", ""),
        }
        for i in verified_issues
    ]
    # Sort issues deterministically by candidate_id, line, and violation_type
    canonical_issues.sort(key=lambda x: (x["candidate_id"], str(x["line"]), x["violation_type"]))

    canonical_evidence = [
        {
            "evidence_id": getattr(e, "evidence_id", ""),
            "canonical_url": getattr(e, "canonical_url", ""),
            "is_mock": bool(getattr(e, "is_mock", False)),
        }
        for e in evidence_items
    ]
    # Sort evidence deterministically by evidence_id
    canonical_evidence.sort(key=lambda x: x["evidence_id"])

    canonical_checks = sorted(list(checks_performed))

    payload = {
        "scan_id": scan_id,
        "created_at": created_at,
        "verdict": verdict,
        "ecosystem": ecosystem,
        "filename": filename,
        "source_sha256": source_sha256,
        "source_length": source_length,
        "evidence_trust": evidence_trust,
        "is_mock": is_mock,
        "summary": summary,
        "checks_performed": canonical_checks,
        "verified_issues": canonical_issues,
        "evidence_items": canonical_evidence,
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ScanRepository:
    """Repository managing local SQLite persistence for APICompass audit history.

    Guarantees:
    - Zero code execution during save or retrieval.
    - No raw source code stored by default (only source SHA-256 fingerprint & character length).
    - Preserves deterministic verdicts, evidence trust states, and mock flags.
    - Separates AI suggestions from verified findings.
    - Parameterized queries protecting against SQL injection.
    - Scoped context connections preventing resource leaks.
    """

    def __init__(self, db_path_override: Optional[Union[str, Path]] = None) -> None:
        self.db_path_override = db_path_override

    def save_scan(self, request: AnalysisRequest, report: AnalysisReport) -> str:
        """Persist a completed analysis report into the audit database.

        Args:
            request: The original AnalysisRequest (used for computing source fingerprint).
            report: The authoritative server-side AnalysisReport produced by the Evidence Court.

        Returns:
            scan_id: Unique server-generated scan identifier.
        """
        # Compute source fingerprint on the server (never trusting client metadata)
        source_sha256 = hashlib.sha256(request.source.encode("utf-8")).hexdigest()
        source_length = len(request.source)

        scan_id = f"scan_{uuid.uuid4().hex[:16]}"
        now_utc = datetime.now(timezone.utc).isoformat()

        # Compute audit integrity hash over canonical report fields
        integrity_hash = compute_record_integrity_hash(
            scan_id=scan_id,
            created_at=now_utc,
            verdict=report.verdict,
            ecosystem=request.ecosystem,
            filename=request.filename[:255],
            source_sha256=source_sha256,
            source_length=source_length,
            evidence_trust=report.evidence_trust,
            is_mock=report.is_mock,
            verified_issues=report.verified_issues,
            evidence_items=report.evidence_items,
            checks_performed=report.checks_performed,
            summary=report.summary,
        )

        # Identify primary abstention reason if applicable
        abstention_reason = None
        if report.candidate_assessments:
            for cand in report.candidate_assessments:
                if cand.abstention_reason:
                    abstention_reason = cand.abstention_reason
                    break
        elif report.verdict == "unable_to_verify" and report.limitations_and_caveats:
            abstention_reason = report.limitations_and_caveats[0].split(":")[0]

        # Requirement 3: Never store API keys, secrets, or auth tokens in history
        clean_summary, _ = scrub_secrets(report.summary)
        clean_abstention = scrub_secrets(abstention_reason)[0] if abstention_reason else None
        clean_checks = [scrub_secrets(c)[0] for c in report.checks_performed]
        clean_limits = [scrub_secrets(l)[0] for l in report.limitations_and_caveats]
        clean_filename, _ = scrub_secrets(request.filename[:255])

        with get_db(self.db_path_override) as conn:
            # 1. Insert main scan record
            conn.execute(
                """
                INSERT INTO scans (
                    scan_id, schema_version, created_at, completed_at, status, verdict,
                    ecosystem, filename, source_sha256, source_length, pipeline_version,
                    evidence_trust, is_mock, llm_reasoning_status, candidates_count,
                    issues_count, evidence_count, suggestions_count, summary,
                    abstention_reason, checks_performed, limitations_and_caveats,
                    disclaimer, integrity_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id,
                    1,
                    now_utc,
                    now_utc,
                    "completed",
                    report.verdict,
                    request.ecosystem,
                    clean_filename,
                    source_sha256,
                    source_length,
                    report.engine_version,
                    report.evidence_trust,
                    1 if report.is_mock else 0,
                    report.llm_reasoning_status,
                    len(report.candidate_assessments),
                    len(report.verified_issues),
                    len(report.evidence_items),
                    len(report.ai_suggestions),
                    clean_summary,
                    clean_abstention,
                    json.dumps(clean_checks),
                    json.dumps(clean_limits),
                    report.disclaimer,
                    integrity_hash,
                ),
            )

            # 2. Insert evidence audit records
            for ev in report.evidence_items:
                stored_excerpt = ev.content_excerpt[:4000]
                clean_excerpt, _ = scrub_secrets(stored_excerpt)
                clean_title, _ = scrub_secrets(ev.title)
                ev_hash = hashlib.sha256(clean_excerpt.encode("utf-8")).hexdigest()
                conn.execute(
                    """
                    INSERT INTO scan_evidence (
                        scan_id, evidence_id, ecosystem, package, source_url, canonical_url,
                        title, content_excerpt, retrieved_at, provider, status, is_mock,
                        source_trust, doc_version, content_sha256, verdict_influence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        ev.evidence_id,
                        ev.ecosystem,
                        ev.package,
                        ev.source_url,
                        ev.canonical_url,
                        clean_title,
                        clean_excerpt,
                        ev.retrieved_at,
                        ev.provider,
                        ev.status,
                        1 if ev.is_mock else 0,
                        ev.source_trust,
                        ev.doc_version,
                        ev_hash,
                        "adjudicated_evidence",
                    ),
                )

            # 3. Insert verified issues (deterministic findings)
            for issue in report.verified_issues:
                clean_explanation, _ = scrub_secrets(issue.explanation)
                clean_issue_json, _ = scrub_secrets(issue.model_dump_json())
                conn.execute(
                    """
                    INSERT INTO scan_findings (
                        scan_id, finding_type, candidate_id, category, source_line,
                        message, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        "verified_issue",
                        issue.candidate_id,
                        issue.violation_type,
                        issue.source_location.lineno,
                        clean_explanation,
                        clean_issue_json,
                    ),
                )

            # 4. Insert AI suggestions (strictly separated as advisory)
            for suggestion in report.ai_suggestions:
                clean_desc, _ = scrub_secrets(suggestion.description)
                clean_sug_json, _ = scrub_secrets(suggestion.model_dump_json())
                conn.execute(
                    """
                    INSERT INTO scan_findings (
                        scan_id, finding_type, candidate_id, category, source_line,
                        message, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        "ai_suggestion",
                        suggestion.candidate_id,
                        suggestion.claim_type,
                        None,
                        clean_desc,
                        clean_sug_json,
                    ),
                )

        logger.info(
            "Persisted scan audit record %s (verdict: %s, issues: %d, mock: %s)",
            scan_id,
            report.verdict,
            len(report.verified_issues),
            report.is_mock,
        )
        return scan_id

    def save_project_scan(
        self,
        request: ProjectAnalysisRequest,
        report: ProjectAnalysisReport,
    ) -> str:
        """Persist a completed multi-file project analysis report into the audit database.

        Args:
            request: The original ProjectAnalysisRequest (used for computing source fingerprint).
            report: The authoritative ProjectAnalysisReport produced by the Evidence Court.

        Returns:
            scan_id: Unique server-generated scan identifier.
        """
        # Deterministically compute combined source manifest and fingerprint on the server
        sorted_files = sorted(request.files, key=lambda f: f.path)
        file_hashes: Dict[str, str] = {}
        manifest_lines: List[str] = []
        for f in sorted_files:
            f_hash = hashlib.sha256(f.content.encode("utf-8")).hexdigest()
            file_hashes[f.path] = f_hash
            manifest_lines.append(f"{f.path}:{f_hash}")

        combined_manifest = "\n".join(manifest_lines)
        source_sha256 = hashlib.sha256(combined_manifest.encode("utf-8")).hexdigest()
        source_length = sum(len(f.content) for f in request.files)

        scan_id = f"scan_{uuid.uuid4().hex[:16]}"
        now_utc = datetime.now(timezone.utc).isoformat()
        display_filename = f"project:{request.project_name} ({len(request.files)} files)"[:255]

        # Compute audit integrity hash over canonical report fields
        integrity_hash = compute_record_integrity_hash(
            scan_id=scan_id,
            created_at=now_utc,
            verdict=report.verdict,
            ecosystem=request.ecosystem,
            filename=display_filename,
            source_sha256=source_sha256,
            source_length=source_length,
            evidence_trust=report.evidence_trust,
            is_mock=report.is_mock,
            verified_issues=report.verified_issues,
            evidence_items=report.evidence_items,
            checks_performed=report.checks_performed,
            summary=report.summary,
        )

        abstention_reason = None
        if report.syntax_errors_count > 0:
            abstention_reason = "SYNTAX_ERRORS_IN_PROJECT"
        elif report.unresolved_candidates:
            abstention_reason = "UNRESOLVED_CANDIDATES"
        elif report.verdict == "unable_to_verify" and report.limitations_and_caveats:
            abstention_reason = report.limitations_and_caveats[0].split(":")[0]

        # Requirement 3: Never store API keys, secrets, or auth tokens in history
        clean_summary, _ = scrub_secrets(report.summary)
        clean_abstention = scrub_secrets(abstention_reason)[0] if abstention_reason else None
        clean_checks = [scrub_secrets(c)[0] for c in report.checks_performed]
        clean_limits = [scrub_secrets(l)[0] for l in report.limitations_and_caveats]
        clean_display_filename, _ = scrub_secrets(display_filename)

        with get_db(self.db_path_override) as conn:
            # 1. Insert main scan record (Schema Version 2)
            conn.execute(
                """
                INSERT INTO scans (
                    scan_id, schema_version, created_at, completed_at, status, verdict,
                    ecosystem, filename, source_sha256, source_length, pipeline_version,
                    evidence_trust, is_mock, llm_reasoning_status, candidates_count,
                    issues_count, evidence_count, suggestions_count, summary,
                    abstention_reason, checks_performed, limitations_and_caveats,
                    disclaimer, integrity_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id,
                    2,
                    now_utc,
                    now_utc,
                    "completed",
                    report.verdict,
                    request.ecosystem,
                    clean_display_filename,
                    source_sha256,
                    source_length,
                    report.engine_version,
                    report.evidence_trust,
                    1 if report.is_mock else 0,
                    "disabled",
                    report.total_candidates,
                    len(report.verified_issues),
                    len(report.evidence_items),
                    len(report.ai_suggestions),
                    clean_summary,
                    clean_abstention,
                    json.dumps(clean_checks),
                    json.dumps(clean_limits),
                    report.disclaimer,
                    integrity_hash,
                ),
            )

            # 2. Insert project files audit metadata (zero raw source stored!)
            for f in report.files:
                f_hash = file_hashes.get(f.path, hashlib.sha256(b"").hexdigest())
                f_len = sum(len(file_item.content) for file_item in request.files if file_item.path == f.path)
                syntax_err_msg = f.syntax_error.message if f.syntax_error else None
                clean_syntax_err, _ = scrub_secrets(syntax_err_msg) if syntax_err_msg else (None, 0)
                clean_path, _ = scrub_secrets(f.path)
                conn.execute(
                    """
                    INSERT INTO scan_project_files (
                        scan_id, file_path, source_sha256, source_length, parse_status,
                        candidates_count, syntax_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        clean_path,
                        f_hash,
                        f_len,
                        f.parse_status,
                        len(f.candidates),
                        clean_syntax_err,
                    ),
                )

            # 3. Insert verified issues
            for issue in report.verified_issues:
                details = {
                    "claim_checked": issue.claim_checked,
                    "source_url": issue.source_url,
                    "verified_quote": issue.verified_quote,
                    "match_method": issue.match_method,
                    "supporting_evidence_id": issue.supporting_evidence_id,
                    "limitations": issue.limitations,
                    "file_path": issue.file_path,
                    "code_fragment": issue.code_fragment,
                }
                clean_explanation, _ = scrub_secrets(issue.explanation)
                clean_details_json, _ = scrub_secrets(json.dumps(details))
                conn.execute(
                    """
                    INSERT INTO scan_findings (
                        scan_id, finding_type, candidate_id, category, source_line,
                        message, details_json
                    ) VALUES (?, 'verified_issue', ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        issue.candidate_id,
                        issue.violation_type,
                        issue.source_location.lineno,
                        clean_explanation,
                        clean_details_json,
                    ),
                )

            # 4. Insert evidence receipts
            for ev in report.evidence_items:
                stored_excerpt = (ev.content_excerpt or "")[:4000]
                clean_excerpt, _ = scrub_secrets(stored_excerpt)
                clean_title, _ = scrub_secrets(ev.title)
                ev_hash = hashlib.sha256(clean_excerpt.encode("utf-8")).hexdigest()
                conn.execute(
                    """
                    INSERT INTO scan_evidence (
                        scan_id, evidence_id, ecosystem, package, source_url,
                        canonical_url, title, content_excerpt, retrieved_at, provider,
                        status, is_mock, source_trust, doc_version, content_sha256,
                        verdict_influence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        ev.evidence_id,
                        ev.ecosystem,
                        ev.package,
                        ev.source_url,
                        ev.canonical_url,
                        clean_title,
                        clean_excerpt,
                        ev.retrieved_at,
                        ev.provider,
                        ev.status,
                        1 if ev.is_mock else 0,
                        ev.source_trust,
                        ev.doc_version,
                        ev_hash,
                        "adjudicated_evidence",
                    ),
                )

        logger.info(
            "Persisted project scan audit record %s (verdict: %s, files: %d)",
            scan_id,
            report.verdict,
            len(request.files),
        )
        return scan_id

    def get_scan(self, scan_id: str) -> Optional[HistoricalScanDetail]:
        """Retrieve a stored historical scan snapshot by ID.

        Does not perform external documentation requests or call LLM providers.
        """
        with get_db(self.db_path_override) as conn:
            # 1. Fetch main scan record
            cursor = conn.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,))
            row = cursor.fetchone()
            if not row:
                return None

            # 2. Fetch evidence records
            ev_cursor = conn.execute(
                "SELECT * FROM scan_evidence WHERE scan_id = ? ORDER BY id ASC",
                (scan_id,),
            )
            evidence_items: List[NormalizedEvidence] = []
            for ev_row in ev_cursor.fetchall():
                try:
                    evidence_items.append(
                        NormalizedEvidence(
                            evidence_id=ev_row["evidence_id"],
                            ecosystem=ev_row["ecosystem"],
                            package=ev_row["package"] or "stripe",
                            source_url=ev_row["source_url"],
                            canonical_url=ev_row["canonical_url"],
                            title=ev_row["title"],
                            content_excerpt=ev_row["content_excerpt"],
                            retrieved_at=ev_row["retrieved_at"],
                            provider=ev_row["provider"],
                            status=ev_row["status"],
                            is_mock=bool(ev_row["is_mock"]),
                            source_trust=ev_row["source_trust"],
                            doc_version=ev_row["doc_version"],
                        )
                    )
                except Exception as ev_err:
                    logger.warning("Corrupted evidence row skipped in scan %s: %s", scan_id, ev_err)

            # 3. Fetch findings (verified issues and AI suggestions)
            findings_cursor = conn.execute(
                "SELECT * FROM scan_findings WHERE scan_id = ? ORDER BY id ASC",
                (scan_id,),
            )
            verified_issues: List[VerifiedIssue] = []
            ai_suggestions: List[AISuggestion] = []

            for f_row in findings_cursor.fetchall():
                try:
                    raw_details = f_row["details_json"]
                    details = json.loads(raw_details) if raw_details else {}
                    if f_row["finding_type"] == "verified_issue":
                        verified_issues.append(VerifiedIssue.model_validate(details))
                    elif f_row["finding_type"] == "ai_suggestion":
                        ai_suggestions.append(AISuggestion.model_validate(details))
                except Exception as parse_err:
                    logger.warning("Corrupted finding row skipped in scan %s: %s", scan_id, parse_err)

            # Parse JSON fields safely (Requirement 5: Handle corrupted records gracefully)
            try:
                checks_performed = json.loads(row["checks_performed"]) if row["checks_performed"] else []
                if not isinstance(checks_performed, list):
                    checks_performed = [str(checks_performed)]
            except Exception as e:
                logger.warning("Corrupted checks_performed in scan %s: %s", scan_id, e)
                checks_performed = []

            try:
                limitations_and_caveats = json.loads(row["limitations_and_caveats"]) if row["limitations_and_caveats"] else []
                if not isinstance(limitations_and_caveats, list):
                    limitations_and_caveats = [str(limitations_and_caveats)]
            except Exception as e:
                logger.warning("Corrupted limitations_and_caveats in scan %s: %s", scan_id, e)
                limitations_and_caveats = []

            # 4. Check for project files if this scan was a multi-file project analysis
            proj_cursor = conn.execute(
                "SELECT file_path, source_sha256, source_length, parse_status, candidates_count, syntax_error "
                "FROM scan_project_files WHERE scan_id = ? ORDER BY file_path ASC",
                (scan_id,),
            )
            proj_rows = proj_cursor.fetchall()
            parsed_proj_files: List[ProjectFileDetailSummary] = []
            for r in proj_rows:
                try:
                    parsed_proj_files.append(
                        ProjectFileDetailSummary(
                            file_path=r["file_path"],
                            source_sha256=r["source_sha256"],
                            source_length=r["source_length"],
                            parse_status=r["parse_status"],
                            candidates_count=r["candidates_count"],
                            syntax_error=r["syntax_error"],
                        )
                    )
                except Exception as proj_err:
                    logger.warning("Corrupted project file row skipped in scan %s: %s", scan_id, proj_err)
            project_files = parsed_proj_files if parsed_proj_files else None

            return HistoricalScanDetail(
                scan_id=row["scan_id"],
                is_historical=True,
                schema_version=row["schema_version"],
                created_at=row["created_at"],
                completed_at=row["completed_at"],
                status=row["status"],
                verdict=row["verdict"],
                ecosystem=row["ecosystem"],
                filename=row["filename"],
                source_sha256=row["source_sha256"],
                source_length=row["source_length"],
                pipeline_version=row["pipeline_version"],
                evidence_trust=row["evidence_trust"],
                is_mock=bool(row["is_mock"]),
                llm_reasoning_status=row["llm_reasoning_status"],
                summary=row["summary"],
                abstention_reason=row["abstention_reason"],
                checks_performed=checks_performed,
                verified_issues=verified_issues,
                ai_suggestions=ai_suggestions,
                evidence_items=evidence_items,
                limitations_and_caveats=limitations_and_caveats,
                disclaimer=row["disclaimer"],
                integrity_hash=row["integrity_hash"],
                project_files=project_files,
            )

    def list_scans(
        self,
        limit: int = 20,
        offset: int = 0,
        verdict: Optional[str] = None,
        ecosystem: Optional[str] = None,
        source_sha256: Optional[str] = None,
    ) -> Tuple[List[ScanSummaryItem], int]:
        """Query paginated scan summaries with optional filters.

        Args:
            limit: Maximum items to return (clamped between 1 and 100).
            offset: Offset index for pagination.
            verdict: Optional verdict filter ('clean', 'issues_found', 'unable_to_verify').
            ecosystem: Optional API ecosystem filter.
            source_sha256: Optional source hash filter.

        Returns:
            (items, total_count)
        """
        clamped_limit = max(1, min(limit, 100))
        clamped_offset = max(0, offset)

        clauses: List[str] = []
        params: List[Union[str, int]] = []

        if verdict:
            clauses.append("verdict = ?")
            params.append(verdict)
        if ecosystem:
            clauses.append("ecosystem = ?")
            params.append(ecosystem)
        if source_sha256:
            clauses.append("source_sha256 = ?")
            params.append(source_sha256)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with get_db(self.db_path_override) as conn:
            # Get total count
            count_cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM scans {where_sql}", params)
            total = count_cursor.fetchone()["cnt"]

            # Query page
            query_sql = f"""
                SELECT scan_id, created_at, verdict, ecosystem, filename, source_sha256,
                       source_length, evidence_trust, is_mock, candidates_count,
                       issues_count, evidence_count, suggestions_count, summary, status
                FROM scans
                {where_sql}
                ORDER BY created_at DESC, scan_id DESC
                LIMIT ? OFFSET ?
            """
            cursor = conn.execute(query_sql, params + [clamped_limit, clamped_offset])
            items: List[ScanSummaryItem] = []
            for row in cursor.fetchall():
                try:
                    items.append(
                        ScanSummaryItem(
                            scan_id=row["scan_id"],
                            created_at=row["created_at"],
                            verdict=row["verdict"],
                            ecosystem=row["ecosystem"],
                            filename=row["filename"],
                            source_sha256=row["source_sha256"],
                            source_length=row["source_length"],
                            evidence_trust=row["evidence_trust"],
                            is_mock=bool(row["is_mock"]),
                            candidates_count=row["candidates_count"],
                            issues_count=row["issues_count"],
                            evidence_count=row["evidence_count"],
                            suggestions_count=row["suggestions_count"],
                            summary=row["summary"],
                            status=row["status"],
                        )
                    )
                except Exception as row_err:
                    logger.warning("Corrupted scan summary row skipped: %s", row_err)

        return items, total

    def delete_scan(self, scan_id: str) -> bool:
        """Explicitly delete a scan and its associated evidence and findings.

        Returns:
            True if scan existed and was deleted, False if not found.
        """
        with get_db(self.db_path_override) as conn:
            cursor = conn.execute("SELECT scan_id FROM scans WHERE scan_id = ?", (scan_id,))
            if not cursor.fetchone():
                return False

            conn.execute("DELETE FROM scans WHERE scan_id = ?", (scan_id,))
            logger.info("Explicitly deleted scan audit record %s", scan_id)
            return True

    def link_fix_proposal(self, scan_id: str, proposal: FixProposalResponse) -> bool:
        """Optionally record a generated fix proposal linked to a historical scan record.

        Validates server-side that:
        - proposal_id matches safe identifier format
        - scan_id exists in the database
        - candidate_id belongs to the scan's findings
        - diff stored is the line-bounded unified diff, preserving privacy
        - status reflects generated outcome and is never falsely marked 'applied'
        """
        # 1. Validate proposal_id format
        if not re.match(r"^prop_[a-zA-Z0-9_\-]{8,64}$", proposal.proposal_id):
            logger.warning("Rejected linking proposal with invalid proposal_id: %s", proposal.proposal_id)
            return False

        with get_db(self.db_path_override) as conn:
            # 2. Check scan existence
            cursor = conn.execute("SELECT scan_id FROM scans WHERE scan_id = ?", (scan_id,))
            if not cursor.fetchone():
                logger.warning("Rejected linking proposal %s: scan %s does not exist", proposal.proposal_id, scan_id)
                return False

            # 3. Verify candidate belongs to the target scan
            cand_cursor = conn.execute(
                "SELECT 1 FROM scan_findings WHERE scan_id = ? AND candidate_id = ?",
                (scan_id, proposal.candidate_id),
            )
            if not cand_cursor.fetchone():
                logger.warning(
                    "Rejected linking proposal %s: candidate %s does not belong to scan %s",
                    proposal.proposal_id,
                    proposal.candidate_id,
                    scan_id,
                )
                return False

            now_utc = datetime.now(timezone.utc).isoformat()
            clean_diff, _ = scrub_secrets(proposal.unified_diff) if proposal.unified_diff else (None, 0)
            clean_summary, _ = scrub_secrets(proposal.summary) if proposal.summary else ("", 0)
            conn.execute(
                """
                INSERT OR REPLACE INTO scan_fix_proposals (
                    proposal_id, scan_id, candidate_id, status, diff, syntax_valid,
                    reverification_status, created_at, explanation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.proposal_id,
                    scan_id,
                    proposal.candidate_id,
                    proposal.status,
                    clean_diff,
                    1 if proposal.syntax_valid else 0,
                    proposal.reverification_status,
                    now_utc,
                    clean_summary,
                ),
            )
            logger.info("Linked fix proposal %s to scan %s", proposal.proposal_id, scan_id)
            return True


# Default singleton instance
scan_repository = ScanRepository()


def get_scan_repository() -> ScanRepository:
    """Dependency provider returning singleton scan repository instance."""
    return scan_repository
