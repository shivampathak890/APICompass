# APICompass v3 — Multi-File Project Analysis Audit & Recommendation Report

## 1. Executive Summary

An audit of APICompass's existing multi-file analysis functionality was conducted across the Python/Stripe verification pipeline. 

### Core Verdict
- **End-to-End Status**: Multi-file project analysis **is fully connected end-to-end** across frontend (`ProjectAnalysisView.tsx`), API endpoints (`POST /api/v1/analyze/project`), static AST analyzer, cross-file import graph resolver (`ProjectGraphResolver`), Evidence Court adjudicator (`ProjectAdjudicator`), and SQLite v2 audit persistence (`scan_project_files`).
- **Usefulness for Current MVP**: **Genuinely useful, but strictly bounded in scope**. Python/Stripe codebases commonly partition SDK usage across helper modules (e.g., `services/payment.py` containing `stripe.Charge.create` called by `main.py`). The multi-file analysis accurately parses separate modules, resolves project-local and relative import hierarchies, and adjudicates Stripe API contracts with exact file and line attribution.
- **Architectural Scope**: The implementation is **strictly static AST parsing and import graph resolution**. It does **not** perform whole-program interprocedural data-flow analysis, parameter taint tracking across files, or dynamic runtime module execution.

---

## 2. In-Depth Inspection

### 2.1 File Input Models & Validation
- **Model**: `ProjectAnalysisRequest` and `ProjectFileItem` (`backend/app/schemas/project_analysis.py`).
- **Validation**:
  - Rejects empty paths and whitespace.
  - Rejects NUL bytes (`\0`).
  - Rejects paths exceeding 255 characters.
  - Rejects absolute paths (`/` or `\`), UNC network paths (`//`), and drive letters (`C:`).
  - Traversal components (`..`) are strictly rejected.
  - Normalizes backslashes to forward slashes and strips `./`.
  - Enforces `.py` extension (rejecting bare `.py` and non-Python extensions).
  - Enforces duplicate path detection (case-insensitive) after normalization.
- **Resource Limits**:
  - `MAX_PROJECT_FILES`: 20 files.
  - `MAX_FILE_SIZE_BYTES`: 100 KB per individual file.
  - `MAX_COMBINED_SIZE_BYTES`: 500 KB total project size.

### 2.2 Per-File AST Parsing & Zero Code Execution
- Each submitted file is parsed independently via `ast.parse` in `backend/app/services/python_ast_analyzer.py`.
- **Zero Execution Guarantee**: User source code is never executed, imported, or compiled into bytecode.
- **Fault Isolation**: A syntax error in one file does not halt or corrupt AST parsing or candidate extraction in other valid files.

### 2.3 Cross-File Imports, Aliases & Graph Resolution
- Resolved statically by `ProjectGraphResolver`:
  - **Relative Imports**: Single and multi-dot climbing (`from . import ...`, `from ..services import ...`).
  - **Absolute Project-Local Imports**: Normalized module dot-notation (`from services.payment import ...`).
  - **Top-Level Defined Symbols**: Extracts top-level functions, classes, and assigned variable identifiers per file.
  - **External Imports**: Accurately marked as `external` (e.g. `import stripe`).
  - **Wildcard & Dynamic Imports**: Explicitly labeled as `status="ambiguous"` with honest explanations (`Dynamic import construct prevents deterministic static resolution`).
  - **Circular Import Detection**: Cycle detection without infinite recursion; circular cycles are surfaced in `limitations_and_caveats`.

### 2.4 Finding Locations & UI Navigation
- Each `VerifiedIssue` and `CandidateAssessment` carries explicit `file_path`, `source_location` (`lineno`, `col_offset`), and `code_fragment`.
- In `ProjectAnalysisView.tsx`, clicking "Jump to line" on a `FindingCard` switches the active file tab, sets `targetHighlightLine`, and centers the Monaco editor at the precise line.
- If an active file contains a syntax error, Monaco displays inline syntax error markers via `syntaxError` props.

### 2.5 Documentation Retrieval & Mock Quarantine
- Documentation is retrieved for all detected API candidates across files.
- In mock mode (or with `--mock`), strict quarantine is enforced: mock evidence produces `unable_to_verify` with `MOCK FIXTURE QUARANTINE` and never creates unverified or synthetic findings.

### 2.6 Error Handling & Response Structure
- API returns `ProjectAnalysisReport` with clear metrics: `total_files`, `total_lines`, `parsed_files_count`, `syntax_errors_count`, `resolved_imports_count`, `unresolved_imports_count`, `verified_issues`, `relationships`, and `candidate_assessments`.
- Conservative Verdict Precedence:
  1. Mock Mode -> `unable_to_verify`
  2. Verified Issues Present -> `issues_found` (with caveats if syntax errors exist)
  3. Syntax Errors Present -> `unable_to_verify` (never certifies "clean")
  4. Unresolved Candidates -> `unable_to_verify`
  5. Unresolved/Ambiguous Imports -> `unable_to_verify`
  6. All Candidates Verified Clean -> `clean` (with explicit scope disclaimer)

---

## 3. Clear Boundaries: What Multi-File Analysis Does NOT Do

To prevent misleading claims, APICompass adheres to explicit boundaries:
1. **No Interprocedural Taint / Parameter Tracking Across Files**: If a function in `main.py` passes a parameter to a wrapper function in `payment.py`, parameter values are not propagated across file boundaries.
2. **No Cross-File Variable Aliasing**: If `client = stripe.StripeClient()` is instantiated in `client.py` and imported as `client` in `payment.py`, receiver resolution does not trace the instance assignment across files.
3. **No Execution of `__init__.py`**: Package hierarchies are resolved purely from file path structures, not Python runtime imports.

---

## 4. Recommendation: Should Multi-File Remain Available?

### Verdict: **Keep Multi-File Analysis Available as a Dedicated Workspace View**

**Rationale**:
1. **Fully Stable & Tested**: 47 backend integration/audit tests and 5 Playwright E2E tests pass cleanly with zero failures.
2. **Essential for Stripe Architecture**: Real Stripe integrations are almost never single-file scripts; having multi-file support allows developers to inspect real multi-module layouts (`main.py` + `services/payment.py`).
3. **Isolated from Single-File Workflow**: Multi-file view is accessed via a clean tab switch (`Verification Studio` vs `Multi-File Project` vs `Audit History`). Single-file analysis remains completely decoupled and unaffected.
4. **Honest Scope Labeling**: The UI explicitly describes the feature as **"Static Multi-File AST Inspection & Import Hierarchy Mapping"** with clear disclaimers that interprocedural parameter flow is not evaluated.
