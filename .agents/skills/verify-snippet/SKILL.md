---
name: verify-snippet
description: >-
  Statically verify and adjudicate a Python code snippet or file against Stripe API contracts without opening the web UI.
  Use this skill whenever the user asks to analyze a Python file or code snippet for API deprecations, contract violations,
  or outdated Stripe SDK usage directly from the terminal or CLI.
---

# Verify Snippet Skill

This skill allows the agent to run static AST analysis and deterministic contract verification directly on arbitrary Python code or files using APICompass's in-process evidence engine.

## Capabilities

- **Zero Execution**: Code is parsed strictly as data with Python's built-in `ast` module (no `eval`, `exec`, or dynamic imports).
- **Contract Verification**: Checks against official Stripe API requirements (e.g., deprecated parameters, removed endpoints, required arguments, type contracts).
- **Integrity Badging**: Reports verdicts (`clean`, `issues_found`, `unable_to_verify`), evidence trust status, and mock quarantine indicators.

---

## Usage

### 1. Verify an Inline Code String
```bash
./.venv/bin/python .agents/skills/verify-snippet/scripts/verify_snippet.py --code "import stripe; stripe.Charge.create(amount=2000, currency='usd', source='tok_visa')"
```

### 2. Verify an Existing File
```bash
./.venv/bin/python .agents/skills/verify-snippet/scripts/verify_snippet.py --file path/to/legacy_script.py
```

### 3. Output as JSON
```bash
./.venv/bin/python .agents/skills/verify-snippet/scripts/verify_snippet.py --code "import stripe; stripe.PaymentIntent.create(amount=1000, currency='usd')" --json
```

---

## Verdict Interpretation

- **`clean`**: All identified API calls conform to documented contract requirements without any violations.
- **`issues_found`**: Specific contract violations (deprecated arguments, invalid parameters, removed endpoints) were detected and verified against official documentation quotes.
- **`unable_to_verify`**: Conservative abstention triggered due to offline mock mode quarantine, unverified dynamic variables, syntax errors, or absent documentation.

