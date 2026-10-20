---
name: run-test-suite
description: >-
  Execute unit, integration, security, and frontend test suites for APICompass.
  Use this skill whenever the user asks to run tests, execute pytest, run frontend build checks,
  verify regressions, or validate security and contract matching logic.
---

# Run Test Suite Skill

This skill provides procedures for running APICompass test suites reliably, avoiding virtualenv shebang discrepancies and suppressing harmless Python 3.14 deprecation noise.

## Quick Execution

Use the executable test runner helper:
```bash
# Run quick smoke suite (Health, AST Analyzer, Contract Matcher)
./.agents/skills/run-test-suite/scripts/test_runner.sh quick

# Run all backend unit & integration tests
./.agents/skills/run-test-suite/scripts/test_runner.sh backend

# Run security, quarantine, and audit tests
./.agents/skills/run-test-suite/scripts/test_runner.sh security

# Run AST analyzer tests
./.agents/skills/run-test-suite/scripts/test_runner.sh ast

# Run frontend TypeScript typecheck and Vite build
./.agents/skills/run-test-suite/scripts/test_runner.sh frontend

# Run complete test suite (Backend + Frontend)
./.agents/skills/run-test-suite/scripts/test_runner.sh all
```

---

## Direct Pytest Commands

Always execute pytest via the Python binary (`-m pytest`) rather than calling the pytest binary directly, and set `PYTHONPATH=backend`:

```bash
# Run a specific test file
PYTHONPATH=backend ./.venv/bin/python -m pytest backend/tests/test_health.py -W ignore::DeprecationWarning

# Run a specific test case
PYTHONPATH=backend ./.venv/bin/python -m pytest backend/tests/test_ast_analyzer.py -k "test_charge_create" -W ignore::DeprecationWarning

# Run with coverage report
PYTHONPATH=backend ./.venv/bin/python -m pytest backend/tests/ --cov=app -W ignore::DeprecationWarning
```

---

## Frontend Verification

To verify frontend TypeScript types and build assets:
```bash
cd frontend && npm run build
```

