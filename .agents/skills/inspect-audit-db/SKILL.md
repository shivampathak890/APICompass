---
name: inspect-audit-db
description: >-
  Inspect, query, verify privacy compliance, or reset the local APICompass SQLite audit database (data/apicompass.db).
  Use this skill whenever the user asks to inspect past scans, check scan history, review logged findings,
  verify that source code is not retained, or clear the database.
---

# Inspect Audit DB Skill

This skill provides procedures and CLI tooling to inspect the persistent SQLite audit store located at `data/apicompass.db`.

## Database Schema & Tables

The SQLite database maintains an immutable audit trail of analysis runs:
- **`scans`**: Primary record of each analysis run (timestamp, verdict, trust level, mock flag, source SHA-256 hash, candidate counts).
- **`scan_findings`**: Verified contract violations associated with a scan.
- **`scan_evidence`**: Normalized documentation pieces used during adjudication.
- **`scan_fix_proposals`**: AST-verified fix proposals generated for findings.
- **`scan_project_files`**: Multi-file project scan relationships.
- **`schema_migrations`**: Migration ledger ensuring zero downtime and deterministic schema versions.

---

## Usage

### 1. List Recent Scans
```bash
./.agents/skills/inspect-audit-db/scripts/query_db.py list
# Show up to 25 records:
./.agents/skills/inspect-audit-db/scripts/query_db.py list --limit 25
```

### 2. View Details of a Specific Scan
```bash
./.agents/skills/inspect-audit-db/scripts/query_db.py view <scan_id>
```

### 3. Verify Privacy & Zero-Retention Compliance
Confirms that user code is never stored in the database:
```bash
./.agents/skills/inspect-audit-db/scripts/query_db.py privacy
```

### 4. Clear Scan History
Wipe scan records while preserving schema migrations:
```bash
./.agents/skills/inspect-audit-db/scripts/query_db.py clear
```

