"""
Dependency Injection container for the Privacy Shield microservice.

Wiring strategy: lazy singletons via @property with None-guard.
The container owns the Redis connection pool lifecycle.

Dependency graph (edges = "depends on"):
  tokenize_use_case → detection_port, vault_port, crypto_port
  rehydrate_use_case → vault_port, crypto_port
  flush_use_case → vault_port
  rotate_dek_use_case → vault_port, crypto_port
  crypto_port → vault_adapter (for DEK storage)
  vault_port == vault_adapter
  detection_port == regex_detection_adapter
  metrics → (standalone, no dependencies)
"""
from __future__ import annotations

import redis.asyncio as aioredis

from app.application.create_api_key import CreateApiKeyUseCase
from app.application.flush_request import FlushRequestUseCase
from app.application.rehydrate_text import RehydrateTextUseCase
from app.application.revoke_api_key import RevokeApiKeyUseCase
from app.application.rotate_dek import RotateDekUseCase
from app.application.tokenize_text import TokenizeTextUseCase
from app.domain.ports.api_key_port import ApiKeyPort
from app.domain.ports.crypto_port import CryptoPort
from app.domain.ports.detection_port import DetectionPort
from app.domain.ports.vault_port import VaultPort
from app.infrastructure.adapters.aes_crypto import AesCryptoAdapter
from app.infrastructure.adapters.redis_api_key import RedisApiKeyAdapter
from app.infrastructure.adapters.redis_vault import RedisVaultAdapter
from app.infrastructure.adapters.regex_detection import RegexDetectionAdapter
from app.infrastructure.adapters.ner_detection import NerDetectionAdapter
from app.infrastructure.adapters.composite_detection import CompositeDetectionAdapter
from app.infrastructure.config import Settings
from app.infrastructure.metrics import PrivacyShieldMetrics
from app.infrastructure.telemetry import get_logger

_logger = get_logger("container")


class Container:
  """
  DI container — owns object lifecycle and wires adapters to use cases.

  Call initialize() before first request; call shutdown() on exit.
  Thread/coroutine-safe: properties are read-only after initialization.
  """

  def __init__(self, config: Settings) -> None:
    self.config = config
    self._redis: aioredis.Redis | None = None
    self._vault_adapter: RedisVaultAdapter | None = None
    self._crypto_adapter: AesCryptoAdapter | None = None
    self._detection_adapter: CompositeDetectionAdapter | None = None
    self._ner_adapter: NerDetectionAdapter | None = None
    self._regex_adapter: RegexDetectionAdapter | None = None
    self._tokenize_use_case: TokenizeTextUseCase | None = None
    self._rehydrate_use_case: RehydrateTextUseCase | None = None
    self._flush_use_case: FlushRequestUseCase | None = None
    self._rotate_dek_use_case: RotateDekUseCase | None = None
    self._api_key_adapter: RedisApiKeyAdapter | None = None
    self._create_api_key_use_case: CreateApiKeyUseCase | None = None
    self._revoke_api_key_use_case: RevokeApiKeyUseCase | None = None
    self._metrics: PrivacyShieldMetrics = PrivacyShieldMetrics()

  async def initialize(self) -> None:
    """
    Connect to Redis and validate all dependencies.

    Raises on failure so the application refuses to start with bad config.
    """
    _logger.info("Initializing Privacy Shield container")
    # Password auth via redis://:password@host:port in REDIS_URL
    self._redis = aioredis.from_url(
      self.config.redis_url,
      encoding="utf-8",
      decode_responses=False,
      socket_connect_timeout=5,
      socket_timeout=5,
      retry_on_timeout=True,
      health_check_interval=30,
    )
    await self._redis.ping()
    _logger.info("Redis connection established", extra={"_ps_operation": "init"})

    _ = self.crypto_port
    _logger.info("Privacy Shield container ready")

  async def shutdown(self) -> None:
    """Close the Redis connection pool gracefully."""
    if self._redis is not None:
      await self._redis.aclose()
      _logger.info("Redis connection pool closed")

  @property
  def redis_client(self) -> aioredis.Redis:
    if self._redis is None:
      raise RuntimeError("Container not initialized — call initialize() first")
    return self._redis

  @property
  def _vault_impl(self) -> RedisVaultAdapter:
    """The concrete Redis vault adapter (used by crypto for DEK storage)."""
    if self._vault_adapter is None:
      self._vault_adapter = RedisVaultAdapter(self.redis_client)
    return self._vault_adapter

  @property
  def vault_port(self) -> VaultPort:
    return self._vault_impl

  @property
  def crypto_port(self) -> CryptoPort:
    if self._crypto_adapter is None:
      self._crypto_adapter = AesCryptoAdapter(
        kek=self.config.kek_bytes(),
        vault=self._vault_impl,
      )
    return self._crypto_adapter

  @property
  def detection_port(self) -> DetectionPort:
    if self._detection_adapter is None:
      if self._regex_adapter is None:
        self._regex_adapter = RegexDetectionAdapter()
      if self._ner_adapter is None:
        self._ner_adapter = NerDetectionAdapter(self.config.pii_model_dir)
      self._detection_adapter = CompositeDetectionAdapter(
        regex=self._regex_adapter,
        ner=self._ner_adapter,
      )
    return self._detection_adapter

  @property
  def tokenize_use_case(self) -> TokenizeTextUseCase:
    if self._tokenize_use_case is None:
      self._tokenize_use_case = TokenizeTextUseCase(
        detection=self.detection_port,
        vault=self.vault_port,
        crypto=self.crypto_port,
        token_ttl_seconds=self.config.token_ttl_seconds,
        max_tokens_per_org=self.config.max_tokens_per_org,
      )
    return self._tokenize_use_case

  @property
  def rehydrate_use_case(self) -> RehydrateTextUseCase:
    if self._rehydrate_use_case is None:
      self._rehydrate_use_case = RehydrateTextUseCase(
        vault=self.vault_port,
        crypto=self.crypto_port,
      )
    return self._rehydrate_use_case

  @property
  def flush_use_case(self) -> FlushRequestUseCase:
    if self._flush_use_case is None:
      self._flush_use_case = FlushRequestUseCase(vault=self.vault_port)
    return self._flush_use_case

  @property
  def rotate_dek_use_case(self) -> RotateDekUseCase:
    if self._rotate_dek_use_case is None:
      self._rotate_dek_use_case = RotateDekUseCase(
        vault=self.vault_port,
        crypto=self.crypto_port,
      )
    return self._rotate_dek_use_case

  @property
  def api_key_port(self) -> ApiKeyPort:
    """Lazy singleton: Redis-backed API key adapter."""
    if self._api_key_adapter is None:
      self._api_key_adapter = RedisApiKeyAdapter(self.redis_client)
    return self._api_key_adapter

  @property
  def create_api_key_use_case(self) -> CreateApiKeyUseCase:
    if self._create_api_key_use_case is None:
      self._create_api_key_use_case = CreateApiKeyUseCase(
        api_key_port=self.api_key_port
      )
    return self._create_api_key_use_case

  @property
  def revoke_api_key_use_case(self) -> RevokeApiKeyUseCase:
    if self._revoke_api_key_use_case is None:
      self._revoke_api_key_use_case = RevokeApiKeyUseCase(
        api_key_port=self.api_key_port
      )
    return self._revoke_api_key_use_case

  @property
  def metrics(self) -> PrivacyShieldMetrics:
    """In-memory metrics singleton — always available, never None."""
    return self._metrics
