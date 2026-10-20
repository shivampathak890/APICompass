#!/usr/bin/env python3
"""CLI helper to execute and inspect the APICompass Curated Evaluation Suite.

Supports running all 26 cases, filtering by Case ID, or filtering by expected verdict.
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

from evaluation.runner import run_evaluation_suite, print_suite_report
from evaluation.dataset import EVALUATION_CASES


def main():
    parser = argparse.ArgumentParser(description="APICompass Evaluation Suite Runner")
    parser.add_argument("--case", type=str, help="Specific Case ID to run (e.g., EVAL-01, EVAL-17)")
    parser.add_argument("--category", type=str, help="Filter cases by category substring")
    parser.add_argument("--verdict", choices=["clean", "issues_found", "unable_to_verify"], help="Filter by expected verdict")
    parser.add_argument("--json", action="store_true", help="Output full report in JSON format")

    args = parser.parse_args()

    # Run the suite
    report = asyncio.run(run_evaluation_suite())

    # Apply filters if requested
    results = report.results
    if args.case:
        target = args.case.strip().upper()
        results = [r for r in results if r.case_id.upper() == target]
        if not results:
            print(f"Error: Case ID '{args.case}' not found. Available cases: EVAL-01 to EVAL-26", file=sys.stderr)
            sys.exit(1)

    if args.category:
        cat = args.category.lower()
        results = [r for r in results if cat in r.category.lower()]

    if args.verdict:
        results = [r for r in results if r.expected_verdict == args.verdict]

    report.results = results
    report.total_cases = len(results)
    report.passed_cases = sum(1 for r in results if r.passed)
    report.failed_cases = report.total_cases - report.passed_cases
    report.pass_rate_percentage = round((report.passed_cases / report.total_cases * 100) if report.total_cases else 0.0, 1)

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print_suite_report(report)

    if report.failed_cases > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
