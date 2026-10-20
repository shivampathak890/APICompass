#!/usr/bin/env python3
"""CLI utility to verify a Python code snippet against APICompass API contracts.

Can run directly in-process using the native static AST + adjudication engine.
Displays verified contract findings, official excerpts, SHA-256 hashes, and proposed fixes.
"""

import argparse
import asyncio
import os
import sys

# Ensure repository backend is on Python path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.config import settings
from app.schemas.evidence import AnalysisRequest, AnalysisReport
from app.services.evidence.adjudicator import adjudicator
from app.services.fixes.fix_proposer import FixProposer
from app.schemas.fix_proposal import ProposeFixRequest


def format_report_cli(report: AnalysisReport, source: str):
    print("=" * 80)
    print("              APICOMPASS EVIDENCE ADJUDICATION REPORT")
    print("=" * 80)
    print(f" File:           {report.filename}")
    print(f" Final Verdict:  {report.verdict.upper()}")
    print(f" Evidence Trust: {report.evidence_trust.upper()}")
    print(f" Mode:           {'OFFLINE MOCK MODE' if report.is_mock else 'LIVE RETRIEVAL'}")
    print(f" Summary:        {report.summary}")
    print("-" * 80)

    # 1. Verified Live Issues
    if report.verified_issues:
        print(f"\n[!] VERIFIED FINDINGS ({len(report.verified_issues)} issue(s) confirmed):")
        for idx, issue in enumerate(report.verified_issues, 1):
            loc = f"Line {issue.source_location.lineno}:{issue.source_location.col_offset}" if issue.source_location else "N/A"
            print(f"  {idx}. [{issue.violation_type.upper()}] {issue.title or issue.violation_type} ({loc})")
            print(f"     Severity:    {issue.severity}")
            print(f"     Call:        {issue.detected_call or 'API Call'}")
            print(f"     Explanation: {issue.explanation}")
            if issue.verified_quote or issue.supporting_excerpt:
                quote = issue.verified_quote or issue.supporting_excerpt
                print(f"     Official Excerpt: \"{quote}\"")
                print(f"     Documentation:    {issue.canonical_url or issue.source_url}")
                if issue.content_sha256:
                    print(f"     Evidence Hash:    {issue.content_sha256[:16]}...")

    # 2. Candidate Assessments (including mock-quarantined issues)
    if report.candidate_assessments:
        print(f"\n[*] CANDIDATE ASSESSMENTS ({len(report.candidate_assessments)} candidate(s)):")
        for idx, cand in enumerate(report.candidate_assessments, 1):
            loc = f"Line {cand.source_location.lineno}:{cand.source_location.col_offset}" if cand.source_location else "N/A"
            status_tag = cand.verification_status.upper()
            print(f"  {idx}. [{status_tag}] {cand.target_name or cand.call_expr or 'Call'} ({loc})")
            if cand.issues:
                for issue in cand.issues:
                    print(f"     - Issue Detected: [{issue.violation_type}] {issue.explanation}")
            if cand.is_mock:
                print(f"     - Notice: Quarantined under mock integrity rules (requires live TinyFish for verification)")
            if cand.suggested_action:
                print(f"     - Suggested Action: {cand.suggested_action}")

    # 3. Clean Verdict
    if report.verdict == "clean":
        print("\n[✓] CLEAN: No API contract violations or deprecations detected.")

    # 4. Caveats & Unresolved
    if report.limitations_and_caveats:
        print(f"\n[*] Limitations & Caveats:")
        for cav in report.limitations_and_caveats:
            print(f"  - {cav}")

    if report.unresolved_candidates:
        print(f"\n[*] Unresolved Candidates ({len(report.unresolved_candidates)}):")
        for u in report.unresolved_candidates:
            print(f"  - {u}")

    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Statically verify Python API usage against official contracts")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--code", type=str, help="Python code string to analyze")
    group.add_argument("--file", type=str, help="Path to Python file to analyze")

    parser.add_argument("--filename", type=str, default="snippet.py", help="Logical filename")
    parser.add_argument("--live", action="store_true", help="Force live documentation retrieval mode (MOCK_MODE=false)")
    parser.add_argument("--json", action="store_true", help="Output full report in raw JSON")

    args = parser.parse_args()

    if args.file:
        if not os.path.isfile(args.file):
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        with open(args.file, "r", encoding="utf-8") as f:
            source = f.read()
        filename = os.path.basename(args.file)
    else:
        source = args.code
        filename = args.filename

    if args.live:
        settings.MOCK_MODE = False

    request = AnalysisRequest(
        source=source,
        filename=filename,
        ecosystem="stripe",
    )

    report = asyncio.run(adjudicator.adjudicate(request))

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        format_report_cli(report, source)

    if report.verdict == "issues_found":
        sys.exit(2)
    elif report.verdict == "unable_to_verify":
        sys.exit(0)  # Standard completion with unverified or quarantined output
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
