# privacy-shield/app/application/tokenize_text.py
"""
TokenizeTextUseCase — orchestrate PII detection, token assignment, and vault storage.

This is the central use case for Fase 1. It implements the full tokenization pipeline:
  1. Resolve per-org DEK (creates one if absent)
  2. Detect PII spans via DetectionPort
  3. Fuse overlapping spans via span_fusion domain service
  4. For each span: compute HMAC hash, handle collisions, format token
  5. Store encrypted PII in vault (per-token TTL)
  6. Register token hashes under request_id for later flush
  7. Replace spans in text right-to-left (preserves earlier offsets)
  8. Return TokenizeResult with all metadata

Collision handling:
  Each HMAC[:4] is checked against 'existing_tokens' (caller-supplied carry-over)
  and the in-session collision map built during this call. If the same hash already
  maps to a DIFFERENT plaintext, we try hash+"_2", "_3", etc., until a free slot
  is found. If the same hash already maps to the SAME plaintext (idempotent),
  we reuse the existing token directly without re-encrypting.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.domain.entities import PiiSpan, QuotaExceededError, TokenEntry, TokenizeResult
from app.domain.ports.crypto_port import CryptoPort
from app.domain.ports.detection_port import DetectionPort
from app.domain.ports.vault_port import VaultPort
from app.domain.services.span_fusion import fuse_spans
from app.domain.services.token_format import (
    VALID_TYPES,
    build_collision_hash,
    format_token,
    parse_token,
)

# Maximum collision attempts before raising — 10 is the hard limit aligned with
# build_collision_hash(). More than 10 collisions signals a systemic problem.
_MAX_COLLISION_ATTEMPTS = 10


@dataclass
class _CollisionTracker:
    """
    Per-call collision map: hash_hex → original plaintext.

    Tracks both caller-supplied existing_tokens and newly minted tokens
    within this request so collision detection is consistent across
    multiple spans in a single call.
    """

    # hash_hex → original PII value for all tokens seen in this request
    _seen: dict[str, str] = field(default_factory=dict)

    def seed(self, existing_tokens: dict[str, str]) -> None:
        """Load caller-supplied token carry-over (pii_value → token string)."""
        for pii_value, token_str in existing_tokens.items():
            # token_str format: "[#pe:a3f2]" — extract hash suffix
            parsed = parse_token(token_str)
            if parsed is not None:
                _type, hash_hex = parsed
                self._seen[hash_hex] = pii_value

    def find_or_allocate(self, base_hash: str, pii_value: str) -> str:
        """
        Return a collision-free hash_hex for the given (base_hash, pii_value).

        If base_hash is already claimed by a different value, try "_2", "_3", etc.
        If base_hash maps to the same value, return it (idempotent).
        """
        for attempt in range(1, _MAX_COLLISION_ATTEMPTS + 1):
            candidate = build_collision_hash(base_hash, attempt)
            existing_value = self._seen.get(candidate)
            if existing_value is None:
                # Free slot — claim it
                self._seen[candidate] = pii_value
                return candidate
            if existing_value == pii_value:
                # Same value — reuse
                return candidate
        raise RuntimeError(
            f"Exceeded {_MAX_COLLISION_ATTEMPTS} collision attempts for hash {base_hash!r}. "
            "This indicates a systemic problem — investigate DEK or data anomalies."
        )


class TokenizeTextUseCase:
    """Tokenize a single text string, replacing PII with opaque tokens."""

    def __init__(
        self,
        detection: DetectionPort,
        vault: VaultPort,
        crypto: CryptoPort,
        token_ttl_seconds: int = 60,
        max_tokens_per_org: int = 10_000,
    ) -> None:
        self._detection = detection
        self._vault = vault
        self._crypto = crypto
        self._token_ttl = token_ttl_seconds
        self._max_tokens_per_org = max_tokens_per_org

    async def execute(
        self,
        text: str,
        org_id: str,
        request_id: str,
        existing_tokens: dict[str, str] | None = None,
    ) -> TokenizeResult:
        """
        Tokenize 'text' for the given organization.

        Raises QuotaExceededError if the org has already reached the per-org
        token quota. This prevents a single tenant from exhausting Redis memory
        and evicting other orgs' tokens via LRU pressure.

        Args:
            text:            Raw text to process.
            org_id:          Organization UUID — determines which DEK to use.
            request_id:      UUID tracking this request for later flush.
            existing_tokens: Caller-supplied carry-over map (pii_value → token)
                             from previous turns of the same conversation.

        Returns:
            TokenizeResult with tokenized text, token list, and timing metrics.

        Raises:
            QuotaExceededError: If the org has exceeded max_tokens_per_org.
        """
        t0 = time.perf_counter()

        # Quota check — must happen before any vault writes to prevent Redis
        # memory exhaustion via unbounded single-org token accumulation.
        current_count = await self._vault.count_org_tokens(org_id)
        if current_count >= self._max_tokens_per_org:
            raise QuotaExceededError(org_id, current_count, self._max_tokens_per_org)

        dek = await self._crypto.get_or_create_dek(org_id)
        detection_result = await self._detection.detect(text)
        fused_spans = fuse_spans(detection_result.spans)

        tracker = _CollisionTracker()
        if existing_tokens:
            tracker.seed(existing_tokens)

        token_entries: list[TokenEntry] = []
        # Build a reverse map: pii_value → token_entry for deduplication
        # within this call (same PII appearing multiple times → same token)
        value_to_entry: dict[str, TokenEntry] = {}

        for span in fused_spans:
            pii_value = span.text
            if pii_value in value_to_entry:
                # Same plaintext detected again — reuse the existing token
                token_entries.append(value_to_entry[pii_value])
                continue

            base_hash = self._crypto.hmac_token_hash(dek, pii_value)
            final_hash = tracker.find_or_allocate(base_hash, pii_value)
            token_str = format_token(span.pii_type, final_hash)

            encrypted_value = self._crypto.encrypt(dek, pii_value, associated_data=org_id.encode())
            entry = TokenEntry(
                token=token_str,
                original=pii_value,
                pii_type=span.pii_type,
                token_hash=final_hash,
                encrypted_value=encrypted_value,
                start=span.start,
                end=span.end,
                source=span.source,
            )
            token_entries.append(entry)
            value_to_entry[pii_value] = entry

            # Persist to vault — include request_id in the key so the entry
            # is scoped to this request and cannot be rehydrated cross-request.
            await self._vault.store(
                org_id, request_id, final_hash, encrypted_value, self._token_ttl
            )
            # Register under request for flush
            await self._vault.register_request_token(
                org_id, request_id, final_hash, self._token_ttl
            )

        # Replace spans right-to-left to preserve earlier offsets
        tokenized_text = _replace_spans(text, fused_spans, token_entries)

        tokenization_ms = (time.perf_counter() - t0) * 1000.0
        return TokenizeResult(
            tokenized_text=tokenized_text,
            tokens=token_entries,
            detection_ms=detection_result.detection_ms,
            tokenization_ms=tokenization_ms,
            span_count=len(fused_spans),
        )


def _replace_spans(
    text: str, spans: list[PiiSpan], entries: list[TokenEntry]
) -> str:
    """
    Replace each span in 'text' with its corresponding token string.

    Processes spans in reverse order so that character offsets of earlier
    spans remain valid after each substitution.

    The spans and entries lists are parallel arrays (same index = same span).
    """
    result = list(text)
    # Build (start, end, token) triples, then sort descending by start
    replacements = [
        (span.start, span.end, entry.token)
        for span, entry in zip(spans, entries)
    ]
    for start, end, token in sorted(replacements, key=lambda r: r[0], reverse=True):
        result[start:end] = list(token)
    return "".join(result)
