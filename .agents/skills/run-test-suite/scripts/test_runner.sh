#!/usr/bin/env bash
# Test Runner for APICompass
# Executes backend and frontend test suites reliably using local venv and node packages.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

SUITE="${1:-backend}"

echo "========================================="
echo " APICompass Test Suite Runner ($SUITE)"
echo "========================================="

case "$SUITE" in
    "backend"|"python")
        echo "Running all backend pytest tests..."
        PYTHONPATH=backend "$REPO_ROOT/.venv/bin/python" -m pytest backend/tests/ -W ignore::DeprecationWarning -v
        ;;
    "quick"|"smoke")
        echo "Running quick smoke and health tests..."
        PYTHONPATH=backend "$REPO_ROOT/.venv/bin/python" -m pytest backend/tests/test_health.py backend/tests/test_ast_analyzer.py backend/tests/test_contract_matcher.py -W ignore::DeprecationWarning
        ;;
    "security")
        echo "Running security, quarantine, and audit tests..."
        PYTHONPATH=backend "$REPO_ROOT/.venv/bin/python" -m pytest backend/tests/test_security_audit.py backend/tests/test_mock_mode_audit.py backend/tests/test_documentation_security_hardening.py -W ignore::DeprecationWarning
        ;;
    "ast")
        echo "Running AST analyzer and API call identification tests..."
        PYTHONPATH=backend "$REPO_ROOT/.venv/bin/python" -m pytest backend/tests/test_ast_analyzer*.py backend/tests/test_api_call_identification.py -W ignore::DeprecationWarning
        ;;
    "contracts")
        echo "Running contract matcher and evidence engine tests..."
        PYTHONPATH=backend "$REPO_ROOT/.venv/bin/python" -m pytest backend/tests/test_contract_matcher.py backend/tests/test_evidence_*.py -W ignore::DeprecationWarning
        ;;
    "frontend"|"build")
        echo "Running frontend typecheck and production build..."
        cd "$REPO_ROOT/frontend"
        npm run build
        ;;
    "all")
        echo "Running complete test suite (Backend + Frontend Build)..."
        PYTHONPATH=backend "$REPO_ROOT/.venv/bin/python" -m pytest backend/tests/ -W ignore::DeprecationWarning
        echo ""
        echo "Running frontend build..."
        cd "$REPO_ROOT/frontend"
        npm run build
        ;;
    *)
        # If user passed a specific test file or pytest args
        echo "Running custom pytest args: $@"
        PYTHONPATH=backend "$REPO_ROOT/.venv/bin/python" -m pytest "$@" -W ignore::DeprecationWarning
        ;;
esac

echo ""
echo "========================================="
echo " Test Suite Finished Successfully"
echo "========================================="

