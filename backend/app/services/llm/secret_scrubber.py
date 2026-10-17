"""Secret scrubber and bounded code fragment extractor for LLM reasoning defense.

Ensures that:
1. Hardcoded Stripe secret keys, tokens, credentials, and passwords are never transmitted to LLM providers.
2. Only relevant code fragments around API candidates and imports are extracted, preventing sensitive
   unrelated business logic or large files from being transmitted.
3. Prompt injection delimiters are neutralized in untrusted source code and doc excerpts.
"""

import re
from typing import List, Optional, Set, Tuple

from app.schemas.ast_analysis import ApiCandidate, ImportInfo


# Regex patterns for sensitive keys and tokens
STRIPE_KEY_PATTERNS = [
    (re.compile(r"sk_live_[0-9a-zA-Z_\-]{16,}"), "[REDACTED_STRIPE_LIVE_KEY]"),
    (re.compile(r"sk_test_[0-9a-zA-Z_\-]{16,}"), "[REDACTED_STRIPE_TEST_KEY]"),
    (re.compile(r"rk_live_[0-9a-zA-Z_\-]{16,}"), "[REDACTED_STRIPE_RESTRICTED_KEY]"),
    (re.compile(r"rk_test_[0-9a-zA-Z_\-]{16,}"), "[REDACTED_STRIPE_RESTRICTED_KEY]"),
    (re.compile(r"whsec_[0-9a-zA-Z_\-]{16,}"), "[REDACTED_STRIPE_WEBHOOK_SECRET]"),
    (re.compile(r"pk_live_[0-9a-zA-Z_\-]{16,}"), "[REDACTED_STRIPE_PUBLISHABLE_KEY]"),
    (re.compile(r"pk_test_[0-9a-zA-Z_\-]{16,}"), "[REDACTED_STRIPE_PUBLISHABLE_KEY]"),
]

ASSIGNMENT_PATTERNS = [
    # stripe.api_key = "..."
    (
        re.compile(r"(stripe\.api_key\s*=\s*)(['\"])(?!\[REDACTED_)[^'\"]+(['\"])"),
        r'\1\2[REDACTED_STRIPE_KEY]\3',
    ),
    # Generic credential assignments: api_key = "...", secret = "...", password = "...", db_pass = "..."
    (
        re.compile(
            r"((?:api_key|apikey|secret_key|secret|password|passwd|db_pass|pass|auth_token|client_secret|access_token)\s*=\s*)(['\"])(?!\[REDACTED_)[^'\"]+(['\"])",
            re.IGNORECASE,
        ),
        r'\1\2[REDACTED_SECRET]\3',
    ),
    # Bearer tokens in headers or strings: Bearer eyJ...
    (
        re.compile(r"(Bearer\s+)[A-Za-z0-9\-_\.~+/]+=*", re.IGNORECASE),
        r"\1[REDACTED_TOKEN]",
    ),
]

# Injection tags and delimiters to neutralize in untrusted inputs
INJECTION_DELIMITERS = [
    re.compile(
        r"<\s*/?\s*(?:system|prompt|instruction|untrusted_user_code|untrusted_code_fragments|im_start|im_end|human|assistant)[^>]*>",
        re.IGNORECASE,
    ),
    re.compile(r"<\|im_start\|>|<\|im_end\|>|\[SYSTEM\]|\[/SYSTEM\]", re.IGNORECASE),
]


def scrub_secrets(text: str) -> Tuple[str, int]:
    """Detect and redact sensitive credentials such as Stripe keys, tokens, and passwords.

    Returns:
        Tuple of (scrubbed_text, count_of_redactions)
    """
    if not text:
        return "", 0

    count = 0
    scrubbed = text

    for pattern, replacement in STRIPE_KEY_PATTERNS:
        matches = len(pattern.findall(scrubbed))
        if matches > 0:
            count += matches
            scrubbed = pattern.sub(replacement, scrubbed)

    for pattern, replacement in ASSIGNMENT_PATTERNS:
        matches = len(pattern.findall(scrubbed))
        if matches > 0:
            count += matches
            scrubbed = pattern.sub(replacement, scrubbed)

    return scrubbed, count


def sanitize_untrusted_input(text: str) -> str:
    """Neutralize potential prompt injection tags and delimiters in untrusted text."""
    if not text:
        return ""

    sanitized = text
    for pattern in INJECTION_DELIMITERS:
        sanitized = pattern.sub("[DELIMITER_FILTERED]", sanitized)
    return sanitized


def extract_relevant_code_fragments(
    source: str,
    candidates: List[ApiCandidate],
    imports: Optional[List[ImportInfo]] = None,
    context_lines: int = 2,
    max_total_chars: int = 4000,
) -> str:
    """Extract only the lines of code relevant to detected API candidates and imports.

    Prevents passing entire source files or sensitive unrelated business logic to external LLMs.
    Guarantees:
    - Top-level imports are preserved for library context.
    - Bounded context window around each candidate line.
    - Unrelated code blocks are replaced with a clear omission marker.
    - All secrets within fragments are scrubbed.
    - All prompt injection delimiters are sanitized.
    - Total length is bounded to max_total_chars.
    """
    if not source or not source.strip():
        return ""

    lines = source.splitlines()
    total_lines = len(lines)
    if total_lines == 0:
        return ""

    ranges: List[Tuple[int, int]] = []

    # 1. Include import statements
    if imports:
        for imp in imports:
            start = max(1, imp.location.lineno)
            end = min(total_lines, imp.location.end_lineno or imp.location.lineno)
            ranges.append((start, end))

    # 2. Include bounded windows around candidates
    for cand in candidates:
        start = max(1, cand.location.lineno - context_lines)
        end = min(total_lines, (cand.location.end_lineno or cand.location.lineno) + context_lines)
        ranges.append((start, end))

    # If no candidates or imports were recognized, include the first few lines if small
    if not ranges:
        if total_lines <= 20:
            ranges.append((1, total_lines))
        else:
            ranges.append((1, min(5, total_lines)))

    # 3. Merge overlapping and adjacent ranges
    sorted_ranges = sorted(ranges, key=lambda r: r[0])
    merged_ranges: List[List[int]] = []
    for start, end in sorted_ranges:
        if not merged_ranges:
            merged_ranges.append([start, end])
        else:
            prev_start, prev_end = merged_ranges[-1]
            if start <= prev_end + 1:
                merged_ranges[-1][1] = max(prev_end, end)
            else:
                merged_ranges.append([start, end])

    # 4. Format fragments with line numbers and omission comments
    formatted_chunks: List[str] = []
    last_end = 0

    for start, end in merged_ranges:
        if last_end > 0 and start > last_end + 1:
            formatted_chunks.append("# ... [unrelated code omitted] ...")
        for line_num in range(start, end + 1):
            formatted_chunks.append(f"{line_num}: {lines[line_num - 1]}")
        last_end = end

    if last_end < total_lines:
        formatted_chunks.append("# ... [unrelated code omitted] ...")

    combined_text = "\n".join(formatted_chunks)

    # 5. Scrub secrets and sanitize injection delimiters
    scrubbed, _ = scrub_secrets(combined_text)
    sanitized = sanitize_untrusted_input(scrubbed)

    # 6. Apply character bound
    if len(sanitized) > max_total_chars:
        sanitized = sanitized[:max_total_chars] + "\n# ... [truncated to size limit] ..."

    return sanitized
