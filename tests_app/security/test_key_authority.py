from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import hashlib
import pytest
from fastapi import FastAPI, Depends
from httpx import ASGITransport, AsyncClient
from app.domain.entities import ApiKeyMetadata
from app.infrastructure.adapters.redis_api_key import RedisApiKeyAdapter
from app.infrastructure.adapters.supabase_api_key_loader import SupabaseApiKeyLoader
from app.infrastructure.api.auth import require_api_key

HASH = hashlib.sha256(b'synthetic-key').hexdigest()
META = ApiKeyMetadata('key', 'org', HASH, 'free', 100, True, '', 'live')

def row(**overrides):
    return {'id': 'key', 'org_id': 'org', 'key_hash': HASH, 'active': True,
            'revoked_at': None, 'expires_at': None, 'environment': 'live',
            'ps_organizations': {'plan_id': 'free', 'ps_plans': {'rate_limit_per_minute': 100}}, **overrides}

def loader():
    result = object.__new__(SupabaseApiKeyLoader)
    result._client = MagicMock()
    return result

@pytest.mark.parametrize('change', [
    {'active': False}, {'revoked_at': '2026-01-01T00:00:00Z'},
    {'expires_at': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
    {'expires_at': 'malformed'}, {'expires_at': ''}, {'expires_at': 0},
    {'active': 'false'}, {'expires_at': '2026-01-01'},
    {'ps_organizations': None}, {'ps_organizations': {}},
])
async def test_invalid_authority_wins_over_positive_cache(security_redis, change):
    source = loader()
    current = row()
    source.load_by_hash = lambda key: source._row_to_metadata(current)
    adapter = RedisApiKeyAdapter(security_redis, source)
    await adapter.cache_key(META)
    assert await adapter.validate_key(HASH) is not None
    current.update(change)
    assert await adapter.validate_key(HASH) is None
    assert await security_redis.get(f'ps:apikey:{HASH}') is None

async def test_cold_warm_restart_and_org_deletion(security_redis):
    source = loader()
    current = row()
    source.load_by_hash = lambda key: source._row_to_metadata(current) if current else None
    adapter = RedisApiKeyAdapter(security_redis, source)
    assert await adapter.validate_key(HASH) is not None
    await adapter.cache_key(META)
    current.clear()  # cascade deletion
    assert await adapter.validate_key(HASH) is None
    await security_redis.flushdb()
    assert await adapter.validate_key(HASH) is None
    await adapter.cache_key(META)  # stale warm-up snapshot
    assert await adapter.validate_key(HASH) is None

async def test_control_plane_failure_never_authorizes_cached_key(security_redis):
    source = loader()
    source._client.table.side_effect = ConnectionError('synthetic outage')
    adapter = RedisApiKeyAdapter(security_redis, source)
    await adapter.cache_key(META)
    assert await adapter.validate_key(HASH) is None

async def test_backend_revoke_is_durable_across_restart(security_redis):
    source = loader()
    current = row()
    source.load_by_hash = lambda key: source._row_to_metadata(current)
    def revoke(key):
        current.update(active=False, revoked_at=datetime.now(timezone.utc).isoformat())
        return True
    source.revoke_by_hash = revoke
    adapter = RedisApiKeyAdapter(security_redis, source)
    await adapter.cache_key(META)
    assert await adapter.revoke_key(HASH)
    await security_redis.flushdb()
    assert await adapter.validate_key(HASH) is None

async def test_failed_durable_revocation_is_not_reported_success(security_redis):
    source = loader()
    source.revoke_by_hash = MagicMock(side_effect=ConnectionError('synthetic outage'))
    adapter = RedisApiKeyAdapter(security_redis, source)
    await adapter.cache_key(META)
    with pytest.raises(ConnectionError):
        await adapter.revoke_key(HASH)

async def test_authorization_http_rejects_portal_revocation(security_redis):
    source = loader()
    current = row()
    source.load_by_hash = lambda key: source._row_to_metadata(current)
    adapter = RedisApiKeyAdapter(security_redis, source)
    await adapter.store_key(META)
    app = FastAPI()
    app.state.container = SimpleNamespace(api_key_port=adapter, metrics=MagicMock())
    @app.get('/protected')
    async def protected(ctx=Depends(require_api_key)):
        return {'org_id': ctx['org_id']}
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        assert (await client.get('/protected', headers={'X-Api-Key': 'synthetic-key'})).status_code == 200
        current['active'] = False
        assert (await client.get('/protected', headers={'X-Api-Key': 'synthetic-key'})).status_code == 401

@pytest.mark.parametrize('timestamp', ['2030-01-01T00:00:00Z', '2030-01-01T01:00:00+01:00', None])
def test_valid_expiry(timestamp):
    assert loader()._row_to_metadata(row(expires_at=timestamp)) is not None

def test_expiry_exact_boundary_rejected():
    instant = datetime.now(timezone.utc)
    with patch('app.infrastructure.adapters.supabase_api_key_loader.datetime') as clock:
        clock.fromisoformat.return_value = instant
        clock.now.return_value = instant
        assert loader()._is_expired(instant.isoformat())

def test_revoke_query_updates_source_and_checks_result():
    source = loader()
    source._client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{'id': 'key'}]
    assert source.revoke_by_hash(HASH)
    source._client.table.assert_called_with('ps_api_keys')
    source._client.table.return_value.update.return_value.eq.assert_called_with('key_hash', HASH)

async def test_runtime_creation_written_before_positive_cache(security_redis):
    source = loader()
    source.register_key = MagicMock()
    adapter = RedisApiKeyAdapter(security_redis, source)
    await adapter.store_key(META)
    source.register_key.assert_called_once_with(META)
    assert await security_redis.get(f'ps:apikey:{HASH}') is not None

async def test_failed_creation_not_cached_and_warmup_never_reactivates(security_redis):
    source = loader()
    source.register_key = MagicMock(side_effect=ConnectionError('synthetic outage'))
    adapter = RedisApiKeyAdapter(security_redis, source)
    with pytest.raises(ConnectionError):
        await adapter.store_key(META)
    assert await security_redis.get(f'ps:apikey:{HASH}') is None
    await adapter.cache_key(META)
    assert source.register_key.call_count == 1

async def test_creation_under_limit_source_error_not_swallowed(security_redis):
    source = loader()
    source.register_key = MagicMock(side_effect=ConnectionError('synthetic outage'))
    adapter = RedisApiKeyAdapter(security_redis, source)
    with pytest.raises(ConnectionError):
        await adapter.store_key_if_under_limit(META, 10)
    assert await adapter.validate_key(HASH) is None
