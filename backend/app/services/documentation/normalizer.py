"""Documentation content normalizer and untrusted input defense.

Transforms raw markdown retrieved via TinyFish Fetch into a structured,
normalized document model suitable for API contract comparison while:
1. Preserving source URL, page title, headings, code examples, parameters,
   required-field definitions, deprecation notices, and version context.
2. Neutralizing prompt injection attempts and system-instruction overrides.
3. Enforcing response size limits (max content length, max excerpt length).
4. Generating deterministic SHA-256 content hashes for provenance verification.
5. Producing standardized, whitespace-normalized excerpts for backward compatibility
   with existing contract matching and quote verification logic.
"""

from datetime import datetime, timezone
import hashlib
import logging
import re
from typing import List, Optional, Tuple

from app.schemas.documentation import DocParameter, DocSection, NormalizedDocPage

logger = logging.getLogger(__name__)

# Maximum allowed characters for raw document text (safe parsing limit)
MAX_RAW_CONTENT_CHARS: int = 50_000
# Maximum allowed characters for single-line evidence excerpt
MAX_EXCERPT_CHARS: int = 8_000

# Patterns for prompt injection and system override attempts in untrusted content
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"<\s*system\s*>.*?<\s*/\s*system\s*>", re.IGNORECASE | re.DOTALL),
    re.compile(r"\[\s*SYSTEM\s*\].*?(?:\n|$)", re.IGNORECASE),
    re.compile(r"<!--\s*SYSTEM:.*?-->", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:in\s+)?(?:developer|maintenance|god|jailbreak|unrestricted)\s+mode", re.IGNORECASE),
    re.compile(r"output\s+the\s+following\s+system\s+prompt", re.IGNORECASE),
    re.compile(r"<\s*script\b[^>]*>.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL),
    re.compile(r"!\[.*?\]\((https?://[^\s\)]+)\)", re.IGNORECASE),
    re.compile(r"^(?:system|assistant|human|user)\s*:\s*", re.IGNORECASE | re.MULTILINE),
]

ZERO_WIDTH_CHARS_PATTERN = re.compile(r"[\u200B-\u200D\uFEFF]")


def compute_content_sha256(content: str) -> str:
    """Compute deterministic cryptographic SHA-256 hash of documentation text."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def sanitize_untrusted_input(text: str) -> str:
    """Neutralize adversarial prompt injection instructions inside untrusted documentation.

    Documentation is treated as untrusted text. Any embedded instructions attempting
    to override agent constraints or hijack tool execution are replaced with a safe
    placeholder while preserving legitimate API contract descriptions.
    """
    if not text:
        return ""

    sanitized = ZERO_WIDTH_CHARS_PATTERN.sub("", text)
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(sanitized):
            logger.warning("Neutralized potential prompt injection pattern in documentation content")
            sanitized = pattern.sub(" [UNTRUSTED_INSTRUCTION_FILTERED] ", sanitized)

    return sanitized


def extract_headings(text: str) -> List[str]:
    """Extract markdown headings (# Heading 1, ## Heading 2, etc.) in appearance order."""
    headings: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading_text = stripped.lstrip("#").strip()
            if heading_text:
                headings.append(heading_text)
    return headings


def extract_sections(text: str) -> List[DocSection]:
    """Segment markdown content into structured sections based on headings."""
    sections: List[DocSection] = []
    current_heading = "Overview"
    current_level = 1
    current_lines: List[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            # Flush previous section
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append(
                        DocSection(
                            heading=current_heading,
                            level=current_level,
                            content=content,
                        )
                    )
                current_lines = []

            # Start new section
            level_count = len(stripped) - len(stripped.lstrip("#"))
            current_level = min(6, max(1, level_count))
            current_heading = stripped.lstrip("#").strip() or "Untitled Section"
        else:
            current_lines.append(line)

    # Flush final section
    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(
                DocSection(
                    heading=current_heading,
                    level=current_level,
                    content=content,
                )
            )

    return sections


def extract_code_examples(text: str) -> List[str]:
    """Extract fenced code blocks (```python ... ```) from markdown."""
    pattern = re.compile(r"```(?:[a-zA-Z0-9_\-]+)?\n(.*?)```", re.DOTALL)
    matches = pattern.findall(text)
    return [m.strip() for m in matches if m.strip()]


def extract_parameters_and_contracts(
    text: str,
) -> Tuple[List[DocParameter], List[str], List[str]]:
    """Extract documented API parameters, required fields, and deprecation notices.

    Returns:
        (parameters, required_fields, deprecation_notices)
    """
    parameters: List[DocParameter] = []
    required_fields: List[str] = []
    deprecation_notices: List[str] = []
    seen_params = set()

    # 1. Identify deprecation notices across sentences
    # Sentences containing legacy / deprecated / recommend keywords
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for s in sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        s_low = s_clean.lower()
        if any(kw in s_low for kw in ("legacy", "deprecated", "we recommend using", "replaced by")):
            deprecation_notices.append(s_clean)

    # 2. Identify required fields from structured list items or paragraph text
    # Pattern A: Bullet items: - amount (integer, required): Description
    bullet_param_re = re.compile(
        r"[-*]\s*`?([a-zA-Z0-9_]+)`?\s*(?:\(([^)]*)\))?:\s*(.*)",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        match = bullet_param_re.match(line.strip())
        if match:
            param_name = match.group(1).strip()
            type_info = (match.group(2) or "").strip()
            desc = match.group(3).strip()

            is_req = "required" in type_info.lower() or "required" in desc.lower()[:30]
            is_dep = "deprecated" in type_info.lower() or any(kw in desc.lower() for kw in ("legacy", "deprecated", "recommend", "replaced"))

            if is_req and param_name.lower() not in [r.lower() for r in required_fields]:
                required_fields.append(param_name)

            if param_name not in seen_params:
                seen_params.add(param_name)
                parameters.append(
                    DocParameter(
                        name=param_name,
                        param_type=type_info or None,
                        is_required=is_req,
                        is_deprecated=is_dep,
                        description=desc or None,
                    )
                )

    # Pattern B: Paragraph text: "Required parameters: amount (positive integer), currency (three-letter ISO code)."
    req_match = re.search(r"Required parameters?:\s*([^\.]+)", text, re.IGNORECASE)
    if req_match:
        params_str = req_match.group(1)
        # Match parameter names before optional parenthetical descriptions
        for p in re.findall(r"\b([a-zA-Z0-9_]+)\s*(?:\([^)]*\))?", params_str):
            p_clean = p.strip()
            if p_clean.lower() not in ("positive", "integer", "three", "letter", "iso", "code", "optional", "required"):
                if p_clean.lower() not in [r.lower() for r in required_fields]:
                    required_fields.append(p_clean)
                if p_clean not in seen_params:
                    seen_params.add(p_clean)
                    parameters.append(
                        DocParameter(
                            name=p_clean,
                            param_type=None,
                            is_required=True,
                            is_deprecated=False,
                            description="Documented as required parameter",
                        )
                    )

    return parameters, required_fields, deprecation_notices


def normalize_documentation_content(
    raw_text: str,
    url: str,
    final_url: str,
    title: Optional[str] = None,
    doc_version: Optional[str] = None,
    provider: str = "tinyfish_live",
    is_mock: bool = False,
    retrieved_at: Optional[str] = None,
    max_raw_chars: int = MAX_RAW_CONTENT_CHARS,
    max_excerpt_chars: int = MAX_EXCERPT_CHARS,
) -> Tuple[NormalizedDocPage, str]:
    """Parse, sanitize, and normalize documentation content into a contract-ready model.

    Returns:
        (page_data: NormalizedDocPage, content_excerpt: str)
    """
    now_utc = retrieved_at or datetime.now(timezone.utc).isoformat()

    # 1. Safe parsing & response size limit
    if len(raw_text) > max_raw_chars:
        logger.warning(
            "Raw documentation for %s exceeded %d chars (%d chars); truncating safely",
            url,
            max_raw_chars,
            len(raw_text),
        )
        capped_text = raw_text[:max_raw_chars]
    else:
        capped_text = raw_text

    # 2. Sanitize untrusted input (prompt injection defenses)
    sanitized_text = sanitize_untrusted_input(capped_text)

    # 3. Cryptographic SHA-256 content hash
    content_sha = compute_content_sha256(sanitized_text)

    # 4. Extract structured sections, headings, parameters, code
    headings = extract_headings(sanitized_text)
    sections = extract_sections(sanitized_text)
    code_examples = extract_code_examples(sanitized_text)
    params, req_fields, deprecations = extract_parameters_and_contracts(sanitized_text)

    # 5. Build full normalized document model
    page_data = NormalizedDocPage(
        url=url,
        final_url=final_url,
        title=title,
        doc_version=doc_version,
        content=sanitized_text,
        content_sha256=content_sha,
        headings=headings,
        sections=sections,
        parameters=params,
        required_fields=req_fields,
        deprecation_notices=deprecations,
        code_examples=code_examples,
        is_mock=is_mock,
        provider=provider,
        retrieved_at=now_utc,
        is_full_page=True,
    )

    # 6. Build single-line, whitespace-collapsed excerpt capped at max_excerpt_chars
    # strictly preserving compatibility with test_tinyfish_content_normalization_and_truncation
    collapsed_excerpt = " ".join(sanitized_text.split())[:max_excerpt_chars]

    return page_data, collapsed_excerpt

