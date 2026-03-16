"""
Domain entities for the Privacy Shield microservice.

All entities are immutable (frozen dataclasses). Domain layer has ZERO
infrastructure imports — no Redis, no crypto library references here.
"""
from __future__ import annotations

from dataclasses import dataclass


class QuotaExceededError(Exception):
  """
  Raised when an organization has reached its per-org token quota.

  Callers (routes.py) should map this to HTTP 503 to signal back-pressure
  without exposing internal quota details. The message is safe to surface
  to the API caller.
  """

  def __init__(self, org_id: str, current: int, limit: int) -> None:
    super().__init__(
      f"Organization {org_id!r} has reached the token quota "
      f"({current} >= {limit}). Flush active requests before tokenizing more."
    )
    self.org_id = org_id
    self.current = current
    self.limit = limit


@dataclass(frozen=True)
class PiiSpan:
  """
  A detected PII span within a text string.

  Coordinates are byte-agnostic character offsets into the original text.
  'start' is inclusive, 'end' is exclusive (standard Python slice convention).
  """

  start: int
  end: int
  text: str
  pii_type: str
  source: str
  confidence: float

  def __post_init__(self) -> None:
    if self.start < 0:
      raise ValueError(f"PiiSpan.start must be >= 0, got {self.start}")
    if self.end <= self.start:
      raise ValueError(
        f"PiiSpan.end ({self.end}) must be > start ({self.start})"
      )
    if not (0.0 <= self.confidence <= 1.0):
      raise ValueError(
        f"PiiSpan.confidence must be in [0.0, 1.0], got {self.confidence}"
      )
    if self.source not in ("regex", "slm"):
      raise ValueError(
        f"PiiSpan.source must be 'regex' or 'slm', got {self.source!r}"
      )

  @property
  def length(self) -> int:
    return self.end - self.start

  def overlaps(self, other: "PiiSpan") -> bool:
    """Return True if this span overlaps with 'other' (shared character range)."""
    return self.start < other.end and other.start < self.end

  def is_adjacent_same_type(self, other: "PiiSpan", max_gap: int = 1) -> bool:
    """Return True if spans are adjacent (gap <= max_gap) and share pii_type."""
    if self.pii_type != other.pii_type:
      return False
    gap = max(self.start, other.start) - min(self.end, other.end)
    return 0 <= gap <= max_gap


@dataclass(frozen=True)
class TokenEntry:
  """
  The result of tokenizing one PiiSpan.

  Attributes:
    token: Opaque display string (e.g. "[#pe:a3f2]").
    original: The plaintext PII value that was tokenized.
    pii_type: Two/three-letter code ("pe", "org", "loc", etc.).
    token_hash: 4-char hex suffix, optionally with collision suffix ("a3f2" | "a3f2_2").
    encrypted_value: AES-256-GCM(DEK, original.encode()), stored in the vault.
    start: Inclusive character offset of the span in the original text.
    end: Exclusive character offset of the span in the original text.
    source: Detection source: "regex" | "slm".
  """

  token: str
  original: str
  pii_type: str
  token_hash: str
  encrypted_value: bytes
  start: int
  end: int
  source: str

  def __post_init__(self) -> None:
    if self.start < 0:
      raise ValueError(f"TokenEntry.start must be >= 0, got {self.start}")
    if self.end < self.start:
      raise ValueError(
        f"TokenEntry.end ({self.end}) must be >= start ({self.start})"
      )
    if self.source not in ("regex", "slm"):
      raise ValueError(
        f"TokenEntry.source must be 'regex' or 'slm', got {self.source!r}"
      )


@dataclass(frozen=True)
class DetectionResult:
  """
  The output of a DetectionPort.detect() call.

  Attributes:
    spans: All PII spans found, possibly overlapping (fusion happens upstream).
    detection_ms: Wall-clock milliseconds spent in detection.
    source: Detection method: "regex" | "slm" | "composite".
  """

  spans: list[PiiSpan]
  detection_ms: float
  source: str

  def __post_init__(self) -> None:
    if self.source not in ("regex", "slm", "composite"):
      raise ValueError(
        f"DetectionResult.source must be 'regex', 'slm', or 'composite', "
        f"got {self.source!r}"
      )


@dataclass(frozen=True)
class OrgKeyPair:
  """
  Envelope-encryption key pair for one organization.

  Attributes:
    organization_id: Unique organization identifier.
    encrypted_dek: AES-256-GCM(KEK, raw_dek_bytes), stored in Redis with no TTL.
      The raw DEK is NEVER stored in plain form anywhere outside of in-memory transient use.
  """

  organization_id: str
  encrypted_dek: bytes


@dataclass(frozen=True)
class TokenizeResult:
  """Full output of a single TokenizeTextUseCase execution over one text string."""

  tokenized_text: str
  tokens: list[TokenEntry]
  detection_ms: float
  tokenization_ms: float
  span_count: int


@dataclass(frozen=True)
class RehydrateResult:
  """Full output of a single RehydrateTextUseCase execution."""

  text: str
  rehydrated_count: int
  duration_ms: float


@dataclass(frozen=True)
class FlushResult:
  """Full output of a single FlushRequestUseCase execution."""

  flushed_count: int


@dataclass(frozen=True)
class ApiKeyMetadata:
  """
  Metadata stored alongside a hashed API key in Redis.

  The raw key is NEVER stored — only the SHA-256 hash is persisted.
  The hash is used as the Redis key suffix so the adapter can look up
  metadata from any service instance given the raw key from the caller.

  Attributes:
    key_id: Unique identifier for the key.
    org_id: Organization that owns this key.
    key_hash: SHA-256 hash of the raw API key.
    plan: Subscription plan name.
    rate_limit_per_minute: Maximum API calls per minute for this key.
    active: Whether the key is currently active (not revoked).
    created_at: ISO 8601 timestamp of key creation.
    environment: "live" or "test".
  """

  key_id: str
  org_id: str
  key_hash: str
  plan: str
  rate_limit_per_minute: int
  active: bool
  created_at: str
  environment: str

  def __post_init__(self) -> None:
    if self.environment not in ("live", "test"):
      raise ValueError(
        f"environment must be 'live' or 'test', got {self.environment!r}"
      )
    if self.rate_limit_per_minute < 1:
      raise ValueError(
        f"rate_limit_per_minute must be >= 1, got {self.rate_limit_per_minute}"
      )


@dataclass(frozen=True)
class UsageRecord:
  """Monthly usage snapshot for one organization."""

  org_id: str
  month: str
  tokenize_calls: int
  rehydrate_calls: int
  flush_calls: int
  total_tokens_created: int
