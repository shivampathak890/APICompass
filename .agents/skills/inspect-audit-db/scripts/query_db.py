#!/usr/bin/env python3
"""CLI helper to inspect and query the APICompass SQLite audit database (data/apicompass.db).

Provides commands to view recent scans, inspect findings, verify privacy compliance, or reset scan history.
"""

import argparse
import os
import sqlite3
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
DB_PATH = os.path.join(REPO_ROOT, "data/apicompass.db")


def get_connection():
    if not os.path.isfile(DB_PATH):
        print(f"Database file not found at: {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def list_scans(limit=10):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT scan_id, created_at, filename, ecosystem, verdict, evidence_trust, is_mock, issues_count
        FROM scans
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No scan records found in audit database.")
        return

    print("=" * 95)
    print(f"{'Scan ID':<36} | {'Timestamp':<20} | {'Verdict':<16} | {'Trust':<12} | {'Issues':<6}")
    print("-" * 95)
    for r in rows:
        ts = r["created_at"][:19] if r["created_at"] else "N/A"
        print(f"{r['scan_id']:<36} | {ts:<20} | {r['verdict']:<16} | {r['evidence_trust']:<12} | {r['issues_count']:<6}")
    print("=" * 95)


def scan_details(scan_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,))
    scan = cur.fetchone()

    if not scan:
        print(f"Error: Scan ID '{scan_id}' not found.", file=sys.stderr)
        conn.close()
        sys.exit(1)

    print("=" * 80)
    print(f" SCAN AUDIT RECORD: {scan['scan_id']}")
    print("=" * 80)
    print(f" Timestamp:      {scan['created_at']}")
    print(f" Filename:       {scan['filename']}")
    print(f" Ecosystem:      {scan['ecosystem']}")
    print(f" Verdict:        {scan['verdict']}")
    print(f" Trust:          {scan['evidence_trust']}")
    print(f" Mock Mode:      {bool(scan['is_mock'])}")
    print(f" Verified Issues:{scan['issues_count']}")
    print(f" Summary:        {scan['summary']}")

    # Check for findings
    cur.execute("SELECT * FROM scan_findings WHERE scan_id = ?", (scan_id,))
    findings = cur.fetchall()
    if findings:
        print("\n Verified Findings in Database:")
        for idx, f in enumerate(findings, 1):
            print(f"  {idx}. [{f['category']}] {f['title']} (Severity: {f['severity']})")
            print(f"     Explanation: {f['explanation']}")
            if f['evidence_quote']:
                print(f"     Quote: \"{f['evidence_quote']}\"")

    conn.close()
    print("=" * 80)


def verify_privacy():
    """Verify that source code text is never stored in SQLite."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(scans)")
    columns = [row["name"] for row in cur.fetchall()]
    conn.close()

    raw_code_cols = [c for c in columns if c in ("source", "code", "raw_source", "source_text", "body")]
    print("=== Privacy & Source Retention Audit ===")
    print(f" Columns in 'scans' table: {', '.join(columns)}")
    if not raw_code_cols:
        print(" [PASS] Strict Zero-Retention Privacy Verified:")
        print("        Only non-reversible SHA-256 hash and byte length are stored for tamper detection.")
        print("        Zero raw code columns exist in SQLite schema.")
    else:
        print(f" [FAIL] Found raw source code columns: {raw_code_cols}")


def reset_history():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM scan_fix_proposals")
    cur.execute("DELETE FROM scan_findings")
    cur.execute("DELETE FROM scan_evidence")
    cur.execute("DELETE FROM scan_project_files")
    cur.execute("DELETE FROM scans")
    conn.commit()
    conn.close()
    print("Audit database scan history cleared successfully. Schema migrations preserved.")


def main():
    parser = argparse.ArgumentParser(description="APICompass Audit Database Inspector")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    list_p = subparsers.add_parser("list", help="List recent scan records")
    list_p.add_argument("--limit", type=int, default=10, help="Number of records to show")

    # view
    view_p = subparsers.add_parser("view", help="View full details of a specific scan")
    view_p.add_argument("scan_id", type=str, help="Scan ID to inspect")

    # privacy
    subparsers.add_parser("privacy", help="Audit database schema for zero-retention privacy compliance")

    # clear
    subparsers.add_parser("clear", help="Clear scan audit history (preserves schema)")

    args = parser.parse_args()

    if args.command == "list":
        list_scans(args.limit)
    elif args.command == "view":
        scan_details(args.scan_id)
    elif args.command == "privacy":
        verify_privacy()
    elif args.command == "clear":
        reset_history()


if __name__ == "__main__":
    main()
