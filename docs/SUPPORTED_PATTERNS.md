# Supported Code Patterns in APICompass

This document describes the API call identification layer in APICompass for Python Stripe code, explaining recognized syntax patterns, resolution rules, ambiguity handling, and false-positive prevention.

---

## 1. Overview of the Identification Layer

The API call identification layer (`backend/app/services/identification/call_identifier.py`) parses Python source code into an Abstract Syntax Tree (AST) using Python's standard `ast` module. It performs static symbol resolution without executing untrusted code or importing runtime packages.

Each recognized or candidate call is mapped to a structured representation (`IdentifiedApiCall`):

```json
{
  "call_id": "call_1_0_charge_create",
  "sdk_or_library": "stripe",
  "api_resource": "Charge",
  "operation": "create",
  "symbol": "stripe.Charge.create",
  "positional_arguments": [],
  "keyword_arguments": ["amount", "currency", "source"],
  "location": {
    "start_line": 1,
    "start_column": 0,
    "end_line": 1,
    "end_column": 55
  },
  "confidence": "high",
  "is_ambiguous": false,
  "unresolved_ambiguity": null
}
```

---

## 2. Supported Code Patterns

### 2.1 Direct SDK Invocations
Direct calls on imported Stripe modules or symbols:
```python
import stripe

charge = stripe.Charge.create(
    amount=2000,
    currency="usd",
    source="tok_visa"
)
```
- **Library**: `stripe`
- **Resource**: `Charge`
- **Operation**: `create`
- **Symbol**: `stripe.Charge.create`
- **Confidence**: `high`
- **Ambiguity**: `false`

### 2.2 Aliased Module Imports
Calls using aliased module names (`import stripe as s`):
```python
import stripe as s

intent = s.PaymentIntent.create(
    amount=5000,
    currency="usd"
)
```
- **Library**: `stripe`
- **Resource**: `PaymentIntent`
- **Operation**: `create`
- **Symbol**: `stripe.PaymentIntent.create`
- **Confidence**: `high`
- **Ambiguity**: `false`

### 2.3 Direct Symbol Imports and Aliases
Calls using symbols imported directly from the `stripe` package:
```python
from stripe import Charge as C, PaymentIntent

c = C.create(amount=1000, currency="eur")
pi = PaymentIntent.retrieve("pi_12345")
```
- Fully resolves `C` to `stripe.Charge` and `PaymentIntent` to `stripe.PaymentIntent`.
- **Confidence**: `high`
- **Ambiguity**: `false`

### 2.4 StripeClient Instance Methods (Modern SDK Pattern)
Calls on instances instantiated from `stripe.StripeClient`:
```python
import stripe

client = stripe.StripeClient("sk_test_123")
charge = client.charges.create(amount=1000, currency="usd")
```
- Tracks `client` as an authenticated `stripe.StripeClient` instance.
- Maps resource sub-services (`charges` -> `Charge`, `customers` -> `Customer`, `payment_intents` -> `PaymentIntent`).
- **Confidence**: `high`
- **Ambiguity**: `false`

---

## 3. Disambiguation and False-Positive Prevention

### 3.1 Misleading Common Method Verbs
A major hazard in AST analysis is assuming that generic verbs (`create`, `retrieve`, `update`, `delete`, `list`, `search`) always belong to Stripe.

APICompass enforces strict context checking:
```python
# Non-Stripe code
db.create(table="users", data={})
user_service.retrieve(user_id=123)
cache.delete("session_token")
repository.update(entity)
```
- When a generic verb is called on a receiver that cannot be tied to Stripe imports, aliases, or client instances, it is **rejected immediately** and not emitted as a Stripe candidate.

### 3.2 Substring Collision Avoidance
Receivers with names that merely *contain* substrings of Stripe resources (such as `incharge.create()`, `custom_payment_intent.process()`) are **not** treated as Stripe resources unless explicit symbol tracking ties them to `stripe`.

---

## 4. Ambiguity Preservation and Honest Abstention

When an operation appears plausibly related to Stripe (e.g. within an integration module) but the static context cannot prove provenance, APICompass marks it as **ambiguous**:

### 4.1 Untyped Function Parameters
```python
def process(client):
    # Receiver 'client' is an untyped parameter; type cannot be statically proven
    client.charges.create(amount=100)
```
- Emitted with:
  - `confidence`: `"low"`
  - `is_ambiguous`: `true`
  - `unresolved_ambiguity`: `"Receiver 'client' is a function parameter; runtime type cannot be statically determined without type annotations."`

### 4.2 Dynamic Factory Invocations
```python
client = get_payment_client()
client.charges.create(amount=100)
```
- Emitted with:
  - `confidence`: `"low"`
  - `is_ambiguous`: `true`
  - `unresolved_ambiguity`: `"Client assigned from dynamic call 'get_payment_client()'; runtime type cannot be statically proven."`

### 4.3 Unsupported or Non-Existent Operations
```python
import stripe
stripe.Charge.teleport(destination="mars")
```
- Recognizes the receiver `stripe.Charge`, but identifies `teleport` as not part of known standard operations.
- Emitted with:
  - `confidence`: `"low"`
  - `is_ambiguous`: `true`
  - `unresolved_ambiguity`: `"Method 'teleport' is not a recognized operation for 'stripe.Charge'."`

---

## 5. Downstream Contract Matching Guardrails

To prevent false alarms and hallucinations:
1. **Ambiguity Guard**: Any `IdentifiedApiCall` or `ApiCandidate` with `is_ambiguous = True` is intercepted before contract verification.
2. **Zero Defamation**: The system explicitly **abstains** from generating definitive contract violations (e.g., `legacy_deprecated_parameter` or `missing_required_parameter`) for ambiguous candidates.
3. **Transparent Evidence**: The evaluation report states the ambiguity rationale directly, preserving honest provenance.

---

## 6. Endpoints

- `POST /api/v1/identify/python`: Analyzes source code and returns `IdentifyApiCallsResponse` containing all detected calls, locations, and ambiguity assessments.
- `POST /api/v1/analyze/python`: Runs the end-to-end pipeline (AST analysis $\rightarrow$ API identification $\rightarrow$ documentation retrieval $\rightarrow$ contract matching $\rightarrow$ evidence adjudication).

