# privacy-shield/app/domain/services/token_format.py
"""
Pure domain service: Privacy Shield token format utilities.

Token format: [#<pii_type>:<hash>]
  - pii_type: 2–3 lowercase letters from VALID_TYPES
  - hash:     4–8 lowercase hex chars, optionally followed by a collision suffix (_2, _3, …)

Examples: [#pe:a3f2c1d9]  [#cf:9b1d]  [#org:c4f7ab01_2]

No infrastructure imports. All functions are pure (no side effects).
"""
from __future__ import annotations

import re

# Master token regex — used internally and exported for adapters.
# Hash part accepts 4–8 hex chars to support both legacy 4-char and current 8-char tokens.
TOKEN_PATTERN: re.Pattern[str] = re.compile(
    r"\[#([a-z]{2,3}):([a-f0-9]{4,8}(?:_\d+)?)\]"
)

# Full set of valid PII type codes (authoritative list)
VALID_TYPES: frozenset[str] = frozenset(
    {
        "pe",   # Persona
        "org",  # Organizzazione
        "loc",  # Località
        "ind",  # Indirizzo
        "tel",  # Telefono
        "em",   # Email
        "cf",   # Codice Fiscale
        "ib",   # IBAN
        "med",  # Medico
        "leg",  # Legale
        "rel",  # Relazione
        "fin",  # Finanziario
        "pro",  # Professione
        "dt",   # Data nascita
    }
)


def format_token(pii_type: str, hash_hex: str) -> str:
    """
    Create a canonical Privacy Shield token string.

    Args:
        pii_type: A code from VALID_TYPES (e.g. "pe").
        hash_hex: 4–8 char hex string, possibly with collision suffix ("a3f2c1d9" or "a3f2c1d9_2").

    Returns:
        "[#pe:a3f2c1d9]" or "[#pe:a3f2c1d9_2]"

    Raises:
        ValueError: If pii_type is not in VALID_TYPES or hash_hex has wrong format.
    """
    if pii_type not in VALID_TYPES:
        raise ValueError(
            f"Unknown pii_type {pii_type!r}. Valid types: {sorted(VALID_TYPES)}"
        )
    if not re.fullmatch(r"[a-f0-9]{4,8}(?:_\d+)?", hash_hex):
        raise ValueError(
            f"hash_hex must be 4–8 hex chars with optional '_N' suffix, got {hash_hex!r}"
        )
    return f"[#{pii_type}:{hash_hex}]"


def parse_token(token_str: str) -> tuple[str, str] | None:
    """
    Extract (pii_type, hash_hex) from a token string.

    Args:
        token_str: A potential token string.

    Returns:
        (pii_type, hash_hex) if valid, None if not a token.
    """
    m = TOKEN_PATTERN.fullmatch(token_str)
    if m is None:
        return None
    pii_type, hash_hex = m.group(1), m.group(2)
    if pii_type not in VALID_TYPES:
        return None
    return (pii_type, hash_hex)


def is_token(text: str) -> bool:
    """
    Return True if 'text' is exactly one Privacy Shield token.

    Performs a fullmatch so "[#pe:a3f2] extra" returns False.
    """
    return parse_token(text) is not None


def find_all_tokens(text: str) -> list[tuple[str, str, int, int]]:
    """
    Find all Privacy Shield tokens within 'text'.

    Args:
        text: Arbitrary string possibly containing tokens.

    Returns:
        List of (pii_type, hash_hex, start, end) tuples, ordered by appearance.
        'start' and 'end' are character offsets into 'text'.
    """
    results: list[tuple[str, str, int, int]] = []
    for m in TOKEN_PATTERN.finditer(text):
        pii_type = m.group(1)
        hash_hex = m.group(2)
        if pii_type in VALID_TYPES:
            results.append((pii_type, hash_hex, m.start(), m.end()))
    return results


def build_collision_hash(base_hash: str, attempt: int) -> str:
    """
    Build a collision-suffixed hash token.

    First attempt (attempt=1) returns the base hash unchanged.
    Second attempt (attempt=2) returns "a3f2c1d9_2", and so on.

    Args:
        base_hash: The 4–8 char hex base (e.g. "a3f2c1d9").
        attempt:   Collision attempt number, starting at 1.

    Returns:
        "a3f2c1d9" (attempt=1) or "a3f2c1d9_N" (attempt>=2).

    Raises:
        ValueError: If attempt exceeds 10 — indicates a systemic collision problem.
    """
    if attempt > 10:
        raise ValueError(
            f"Token collision limit exceeded for hash {base_hash!r} after 10 attempts. "
            "This indicates a systemic problem — investigate DEK or data anomalies."
        )
    if attempt <= 1:
        return base_hash
    return f"{base_hash}_{attempt}"
