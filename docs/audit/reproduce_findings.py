"""Read-only audit reproductions: synthetic data and in-process fakeredis only.

Run from the repository root: python3 docs/audit/reproduce_findings.py
These are characterizations of defects, NOT passing security acceptance tests.
No production service, credentials or customer data are used.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fakeredis.aioredis
from cryptography.exceptions import InvalidTag

from app.application.rotate_dek import RotateDekUseCase
from app.infrastructure.adapters.aes_crypto import AesCryptoAdapter
from app.infrastructure.adapters.redis_api_key import RedisApiKeyAdapter
from app.infrastructure.adapters.redis_vault import RedisVaultAdapter
from app.infrastructure.adapters.supabase_api_key_loader import SupabaseApiKeyLoader
from app.infrastructure.telemetry import _JsonFormatter, log_error

ORG = "00000000-0000-0000-0000-000000000001"
REQ = "00000000-0000-0000-0000-000000000002"


async def cache_check():
    redis = fakeredis.aioredis.FakeRedis()
    # Bypass only the network client constructor; use the real row mapper.
    mapper = object.__new__(SupabaseApiKeyLoader)
    row = dict(id="audit-key", org_id=ORG, key_hash="a" * 64,
               active=True, environment="test", created_at="audit",
               expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    metadata = mapper._row_to_metadata(row)
    assert metadata is not None

    class Loader:
        def __init__(self):
            self.calls = 0

        def load_by_hash(self, key_hash):
            self.calls += 1
            return mapper._row_to_metadata(row)

    loader = Loader()
    adapter = RedisApiKeyAdapter(redis, supabase_loader=loader)
    assert await adapter.validate_key(metadata.key_hash) is not None
    row.update(active=False, expires_at="2000-01-01T00:00:00+00:00")
    assert mapper._row_to_metadata(row) is None
    still_valid = await adapter.validate_key(metadata.key_hash)
    ttl = await redis.ttl(adapter._metadata_key(metadata.key_hash))
    assert still_valid is not None and ttl == -1 and loader.calls == 1
    print(json.dumps(dict(check="cached_revocation_expiry", defect_reproduced=True,
                          cache_ttl=ttl, source_reads=loader.calls,
                          expired_revoked_test_key_still_accepted=True)))
    await redis.aclose()


async def rotation_check():
    redis = fakeredis.aioredis.FakeRedis()
    vault = RedisVaultAdapter(redis)
    crypto = AesCryptoAdapter(bytes([1]) * 32, vault)
    old = await crypto.get_or_create_dek(ORG)
    for token in ("aaaaaaaa", "bbbbbbbb"):
        await vault.store(ORG, REQ, token, crypto.encrypt(old, "SYNTHETIC", ORG.encode()), 60)
        await vault.register_request_token(ORG, REQ, token, 60)
    original_store = vault.store
    calls = 0

    async def interrupt_store(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic interruption")
        await original_store(*args)

    with patch.object(vault, "store", interrupt_store):
        try:
            await RotateDekUseCase(vault, crypto).execute(ORG)
        except RuntimeError:
            pass
        else:
            raise AssertionError("interruption not reached")
    result = await RotateDekUseCase(vault, crypto).execute(ORG)
    current = await crypto.get_or_create_dek(ORG)
    unreadable = 0
    for token in ("aaaaaaaa", "bbbbbbbb"):
        try:
            crypto.decrypt(current, await vault.retrieve(ORG, REQ, token), ORG.encode())
        except InvalidTag:
            unreadable += 1
    assert result.rotated and unreadable == 1
    print(json.dumps(dict(check="interrupted_rotation_retry", defect_reproduced=True,
                          reports_success=result.rotated, unreadable_entries=unreadable)))
    await redis.aclose()


def exception_check():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_JsonFormatter())
    logger = logging.getLogger("audit_synthetic_only")
    logger.handlers = [handler]
    logger.propagate = False
    marker = "SYNTHETIC_SENSITIVE_MARKER"
    try:
        raise ValueError(marker)
    except ValueError as exc:
        log_error(logger, "audit", ORG, "SYNTHETIC", "Generic message", exc)
    assert marker in stream.getvalue()
    print(json.dumps(dict(check="exception_log_sanitization", defect_reproduced=True,
                          exception_payload_preserved=True)))


async def ner_check():
    from app.infrastructure.adapters.ner_detection import NerDetectionAdapter
    from app.infrastructure.adapters.composite_detection import CompositeDetectionAdapter
    from app.infrastructure.adapters.regex_detection import RegexDetectionAdapter
    from app.infrastructure.api.schemas import TokenizeRequest

    ner = NerDetectionAdapter(str(Path(".local/pii-model").resolve()))
    detector = CompositeDetectionAdapter(RegexDetectionAdapter(), ner)
    short = "Il signor Mario Rossi abita a Roma."
    prefix = "Questo documento contiene informazioni generali. " * 130
    long = prefix + short
    TokenizeRequest(texts=[long], organization_id=ORG, request_id=REQ)
    offsets = ner._tokenizer(long, return_offsets_mapping=True, max_length=512,
                             truncation=True)["offset_mapping"]
    covered = max(end for _, end in offsets)
    short_result = await detector.detect(short)
    long_result = await detector.detect(long)
    short_name = any("Mario" in span.text for span in short_result.spans)
    long_name = any("Mario" in span.text for span in long_result.spans)
    assert short_name and not long_name and covered < len(prefix)
    print(json.dumps(dict(check="ner_truncation", defect_reproduced=True,
                          input_characters=len(long), covered_characters=covered,
                          short_name_detected=short_name, tail_name_detected=long_name)))


async def main():
    await cache_check()
    await rotation_check()
    exception_check()
    await ner_check()


if __name__ == "__main__":
    asyncio.run(main())
