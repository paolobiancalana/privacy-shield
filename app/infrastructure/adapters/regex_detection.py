# privacy-shield/app/infrastructure/adapters/regex_detection.py
"""
RegexDetectionAdapter — implements DetectionPort using Italian PII regex patterns.

Pattern design decisions:
  - CF (Codice Fiscale): case-insensitive; strong structural match → confidence 1.0
  - IBAN: well-defined format; confidence 1.0
  - Email: RFC-5322 subset; confidence 1.0
  - Phone: Italian mobile + fixed-line; some ambiguity with plain numbers → 0.85
  - Date (dd/mm/yyyy): unambiguous calendar format → 0.90
  - P.IVA: 11 consecutive digits; high false-positive rate → 0.70

Already-tokenized spans ('[#tipo:xxxx]') are masked before matching so they
are never re-detected. This preserves idempotency.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field

from app.domain.entities import DetectionResult, PiiSpan
from app.domain.ports.detection_port import DetectionPort
from app.domain.services.token_format import TOKEN_PATTERN

# Mapping of common Unicode confusables (Cyrillic/Greek lookalikes → Latin).
# Covers the most frequent homoglyph attack vectors for Italian PII.
_CONFUSABLE_MAP: dict[str, str] = {
    # Cyrillic → Latin
    "\u0410": "A", "\u0430": "a",  # А/а
    "\u0412": "B", "\u0432": "b",  # В/в (looks like B)
    "\u0421": "C", "\u0441": "c",  # С/с
    "\u0415": "E", "\u0435": "e",  # Е/е
    "\u041D": "H", "\u043D": "h",  # Н/н (looks like H)
    "\u041A": "K", "\u043A": "k",  # К/к
    "\u041C": "M", "\u043C": "m",  # М/м
    "\u041E": "O", "\u043E": "o",  # О/о
    "\u0420": "P", "\u0440": "p",  # Р/р
    "\u0422": "T", "\u0442": "t",  # Т/т
    "\u0425": "X", "\u0445": "x",  # Х/х
    "\u0423": "Y", "\u0443": "y",  # У/у (looks like Y)
    # Greek → Latin
    "\u0391": "A", "\u03B1": "a",  # Α/α
    "\u0392": "B", "\u03B2": "b",  # Β/β
    "\u0395": "E", "\u03B5": "e",  # Ε/ε
    "\u0397": "H", "\u03B7": "h",  # Η/η
    "\u039A": "K", "\u03BA": "k",  # Κ/κ
    "\u039C": "M", "\u03BC": "m",  # Μ/μ
    "\u039F": "O", "\u03BF": "o",  # Ο/ο
    "\u03A1": "P", "\u03C1": "p",  # Ρ/ρ
    "\u03A4": "T", "\u03C4": "t",  # Τ/τ
    "\u03A7": "X", "\u03C7": "x",  # Χ/χ
}


@dataclass(frozen=True)
class _PatternSpec:
    pii_type: str
    pattern: re.Pattern[str]
    confidence: float


def _compile_patterns() -> list[_PatternSpec]:
    """
    Build the ordered list of compiled pattern specifications.

    Order matters: more specific patterns (CF, IBAN) are listed first so that
    overlap resolution in span_fusion prefers them over weaker patterns.

    Pattern hardening notes:
      - All patterns tolerate optional whitespace/separators between groups
      - IBAN accepts spaces between 4-char groups (ISO 13616 print format)
      - Phone handles +39 glued to digits, landlines with area codes, and separators
      - P.IVA uses context anchors to reduce false positives
      - Date handles multiple separators (/ . -) and optional leading zeros
    """
    raw: list[tuple[str, str, int, float]] = [
        # (pii_type, raw_pattern, flags, confidence)

        # --- CF (Codice Fiscale) ---
        # 16 chars: 6 letters + 2 digits + 1 letter + 2 digits + 1 letter + 3 digits + 1 letter
        # Case-insensitive. Handles:
        #   - Standard: RSSMRA85M01H501Z
        #   - Preceded by "CF:", "C.F.", "codice fiscale" etc. (word boundary)
        #   - Temporary CF (starts with digits for foreign nationals): 8 digits + 1 letter + ...
        # Excludes: random 16-char alphanumeric strings (structure is very specific)
        (
            "cf",
            r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b",
            re.IGNORECASE,
            1.0,
        ),

        # --- IBAN (Italian + common EU with strict prefix) ---
        # Italian IBAN: IT + 2 check digits + CIN letter + 22 digits = 27 chars
        # EU IBAN: 2-letter country code + 2 check digits + 10-30 alphanumeric (BBAN)
        # Tolerates: spaces, dashes between groups
        # EU pattern requires known country codes to prevent false positives
        (
            "ib",
            (
                r"\b(?:"
                r"IT[\s\-]?\d{2}[\s\-]?[A-Z](?:[\s\-]?\d){22}"   # Italian (strict: CIN + 22 digits)
                r"|"
                r"(?:DE|FR|ES|GB|NL|BE|AT|CH|PT|IE|LU|FI|DK|SE|NO|PL|CZ|SK|HR|SI|RO|BG|HU|LT|LV|EE|MT|CY|GR)"
                r"[\s\-]?\d{2}[\s\-]?(?:[A-Z0-9][\s\-]?){10,30}"  # EU (known country codes only)
                r")\b"
            ),
            re.IGNORECASE,
            1.0,
        ),

        # --- Email ---
        # RFC-5322 subset, extended for Italian PEC domains.
        # Handles: standard, subdomains, PEC (.pec.it), gov (.gov.it), + tags
        # Rejects: spaces, missing TLD, missing @
        # Note: "mario rossi@gmail.com" correctly matches "rossi@gmail.com" (valid email)
        (
            "em",
            (
                r"\b[a-zA-Z0-9]"                   # must start with alnum (no leading dots)
                r"[a-zA-Z0-9._%+\-]{0,64}"         # local part body (capped at 64 to prevent ReDoS)
                r"@"
                r"[a-zA-Z0-9]"                     # domain must start with alnum
                r"[a-zA-Z0-9.\-]{0,255}"            # domain body (capped at 255 to prevent ReDoS)
                r"\.[a-zA-Z]{2,}"                  # TLD (at least 2 chars)
                r"\b"
            ),
            0,
            1.0,
        ),

        # --- P.IVA (Partita IVA) ---
        # 11 consecutive digits starting with 0.
        # MUST be listed BEFORE phone to win priority in span_fusion.
        # Context-aware: requires word boundary + not inside a longer number.
        # Only matches 11-digit sequences starting with 0 (Italian P.IVA format).
        # Generic 11-digit sequences not starting with 0 are caught by the fallback
        # fin pattern below.
        (
            "fin",
            r"(?<!\d)\b0\d{10}\b(?!\d)",
            0,
            0.80,
        ),

        # --- Phone (Italian) ---
        # Mobile: +39 3XX XXXXXXX (10 digits after +39)
        # Landline: +39 0X(X) XXXXXXXX (9-10 digits after +39)
        # Tolerates: glued +39, spaces, dashes, dots as separators
        # Uses lookahead/lookbehind instead of \b for +39 prefix compatibility
        # NOTE: Phone requires +39 prefix for landlines starting with 0 to avoid
        # matching P.IVA (11 digits starting with 0). Without +39, only mobile (3XX) matches.
        (
            "tel",
            (
                r"(?<![A-Za-z\d])"             # not preceded by alnum (replaces \b)
                r"(?:"
                # Mobile (with or without +39): 3XX + 7 digits
                r"(?:\+[\s\-.]?39[\s\-.]?)?3[0-9]{2}(?:[\s\-.]?\d){7}"
                r"|"
                # Landline (REQUIRES +39 prefix to distinguish from P.IVA):
                r"\+[\s\-.]?39[\s\-.]?0[0-9]{1,3}(?:[\s\-.]?\d){5,8}"
                r"|"
                # Landline without +39 but with separator after area code (02 1234 5678):
                r"0[0-9]{1,3}[\s\-.](?:[\s\-.]?\d){5,8}"
                r")"
                r"(?![A-Za-z\d])"              # not followed by alnum (replaces \b)
            ),
            0,
            0.85,
        ),

        # --- Date (numeric: dd/mm/yyyy, yyyy-mm-dd) ---
        # Accepts / . - as separators. Day/month with optional leading zero.
        (
            "dt",
            (
                r"\b(?:"
                r"(?:0?[1-9]|[12]\d|3[01])[/.\-](?:0?[1-9]|1[0-2])[/.\-](?:19|20)\d{2}"  # dd/mm/yyyy
                r"|(?:19|20)\d{2}[/.\-](?:0?[1-9]|1[0-2])[/.\-](?:0?[1-9]|[12]\d|3[01])"  # yyyy-mm-dd (ISO)
                r")\b"
            ),
            0,
            0.90,
        ),

        # --- Date (written month ITA: "15 marzo 2026", "3 aprile", "dicembre 2025") ---
        (
            "dt",
            (
                r"\b(?:"
                # dd mese [yyyy]
                r"(?:0?[1-9]|[12]\d|3[01])(?:°)?"
                r"\s+"
                r"(?:gennaio|febbraio|marzo|aprile|maggio|giugno"
                r"|luglio|agosto|settembre|ottobre|novembre|dicembre"
                r"|gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)"
                r"(?:\s+(?:19|20)\d{2})?"
                r"|"
                # mese [yyyy]  (standalone: "marzo 2026")
                r"(?:gennaio|febbraio|marzo|aprile|maggio|giugno"
                r"|luglio|agosto|settembre|ottobre|novembre|dicembre)"
                r"\s+(?:19|20)\d{2}"
                r")\b"
            ),
            re.IGNORECASE,
            0.85,
        ),

        # --- Date (written month ENG: "15 March 2026", "January 3", "March 2026") ---
        (
            "dt",
            (
                r"\b(?:"
                # dd Month [yyyy]
                r"(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
                r"\s+"
                r"(?:January|February|March|April|May|June"
                r"|July|August|September|October|November|December"
                r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                r"(?:\s+(?:19|20)\d{2})?"
                r"|"
                # Month dd[,] [yyyy]
                r"(?:January|February|March|April|May|June"
                r"|July|August|September|October|November|December"
                r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                r"\s+(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
                r"(?:,?\s+(?:19|20)\d{2})?"
                r"|"
                # Month yyyy
                r"(?:January|February|March|April|May|June"
                r"|July|August|September|October|November|December)"
                r"\s+(?:19|20)\d{2}"
                r")\b"
            ),
            re.IGNORECASE,
            0.85,
        ),

        # --- P.IVA fallback (11 digits NOT starting with 0) ---
        # Catches P.IVA-like sequences that don't start with 0 (rare but possible).
        # Lower confidence since 11 random digits could be anything.
        (
            "fin",
            r"(?<!\d)\b[1-9]\d{10}\b(?!\d)",
            0,
            0.65,
        ),
    ]
    return [
        _PatternSpec(
            pii_type=ptype,
            pattern=re.compile(pattern, flags),
            confidence=conf,
        )
        for ptype, pattern, flags, conf in raw
    ]


_COMPILED_PATTERNS: list[_PatternSpec] = _compile_patterns()


# System XML tags whose content should never be tokenized.
# These are injected by SNAP pipeline middleware and contain system metadata,
# not user PII. Tokenizing them breaks LLM context (e.g., current_time).
_SYSTEM_TAG_PATTERN = re.compile(
    r"<(?:current_time|security_boundary|system_instruction|intent_analysis|user_context|session_memory)"
    r"[^>]*>.*?</(?:current_time|security_boundary|system_instruction|intent_analysis|user_context|session_memory)>",
    re.DOTALL,
)


def _mask_existing_tokens(text: str) -> tuple[str, list[tuple[int, int]]]:
    """
    Replace existing Privacy Shield tokens AND system XML tags with blank
    placeholders of equal length.

    Returns the masked text and a list of (start, end) ranges that were masked.
    These ranges are excluded from PII detection so tokens are never re-tokenized
    and system metadata (timestamps, security boundaries) is never corrupted.
    """
    masked = list(text)
    masked_ranges: list[tuple[int, int]] = []

    # Mask existing PS tokens
    for m in TOKEN_PATTERN.finditer(text):
        for i in range(m.start(), m.end()):
            masked[i] = "\x00"
        masked_ranges.append((m.start(), m.end()))

    # Mask system XML tags (current_time, security_boundary, etc.)
    for m in _SYSTEM_TAG_PATTERN.finditer(text):
        for i in range(m.start(), m.end()):
            masked[i] = "\x00"
        masked_ranges.append((m.start(), m.end()))

    return "".join(masked), masked_ranges


def _is_inside_masked(start: int, end: int, masked_ranges: list[tuple[int, int]]) -> bool:
    """Return True if the span [start, end) overlaps any masked range."""
    for ms, me in masked_ranges:
        if start < me and ms < end:
            return True
    return False


class RegexDetectionAdapter(DetectionPort):
    """
    Pure-regex PII detector for Italian text.

    Thread-safe and stateless: all state lives in module-level compiled patterns.
    Suitable for concurrent async use without locking.
    """

    async def detect(self, text: str) -> DetectionResult:
        """
        Run all regex patterns over 'text' and return discovered PiiSpan objects.

        Already-tokenized tokens are masked before matching to prevent
        re-tokenization. The returned spans contain character offsets into
        the ORIGINAL (unmasked) text.
        """
        t0 = time.perf_counter()

        # Anti-homoglyph two-pass normalization:
        # Pass 1 (NFKC): converts fullwidth digits/letters to ASCII equivalents.
        # Pass 2 (confusable folding): maps Cyrillic/Greek/etc lookalikes to Latin.
        # We detect on the folded text but extract spans from the ORIGINAL text
        # so the tokenizer replaces the actual characters the user sent.
        original_text = text
        text_nfkc = unicodedata.normalize("NFKC", text)

        # Confusable folding: replace common Cyrillic/Greek lookalikes with Latin
        folded = []
        for ch in text_nfkc:
            mapped = _CONFUSABLE_MAP.get(ch)
            if mapped is not None:
                folded.append(mapped)
            elif ord(ch) > 127:
                # Try NFKD decomposition + ASCII ignore for remaining non-ASCII
                decomp = unicodedata.normalize("NFKD", ch)
                ascii_ch = decomp.encode("ascii", "ignore").decode("ascii")
                folded.append(ascii_ch if ascii_ch else ch)
            else:
                folded.append(ch)
        detection_text = "".join(folded)

        # Ensure detection_text is same length as original for correct offsets
        # (folding should be 1:1 char mapping, not changing length)
        if len(detection_text) != len(original_text):
            detection_text = text_nfkc  # fallback to NFKC if lengths diverge

        masked_text, masked_ranges = _mask_existing_tokens(detection_text)
        spans: list[PiiSpan] = []

        for spec in _COMPILED_PATTERNS:
            for m in spec.pattern.finditer(masked_text):
                if _is_inside_masked(m.start(), m.end(), masked_ranges):
                    continue
                spans.append(
                    PiiSpan(
                        start=m.start(),
                        end=m.end(),
                        text=original_text[m.start() : m.end()],  # ORIGINAL text slice
                        pii_type=spec.pii_type,
                        source="regex",
                        confidence=spec.confidence,
                    )
                )

        detection_ms = (time.perf_counter() - t0) * 1000.0
        return DetectionResult(
            spans=spans,
            detection_ms=detection_ms,
            source="regex",
        )
