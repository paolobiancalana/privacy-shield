import asyncio
from unittest.mock import patch
import pytest
from cryptography.exceptions import InvalidTag
from app.application.rotate_dek import RotateDekUseCase
from app.application.tokenize_text import TokenizeTextUseCase
from app.application.rehydrate_text import RehydrateTextUseCase
from app.infrastructure.adapters.redis_vault import RedisVaultAdapter
from app.infrastructure.adapters.aes_crypto import AesCryptoAdapter
from app.infrastructure.adapters.regex_detection import RegexDetectionAdapter

ORG = '11111111-1111-1111-1111-111111111111'
OTHER = '22222222-2222-2222-2222-222222222222'

async def setup(client, count=2):
    vault = RedisVaultAdapter(client)
    crypto = AesCryptoAdapter(b'x' * 32, vault)
    dek = await crypto.get_or_create_dek(ORG)
    for i in range(count):
        assert await vault.store(ORG, 'req', f'h{i}', crypto.encrypt(dek, f'synthetic-{i}', ORG.encode()), 60)
    return vault, crypto, RotateDekUseCase(vault, crypto)

async def assert_readable(vault, crypto, count=2):
    wrapped, values = await vault.retrieve_batch_with_dek(ORG, 'req', [f'h{i}' for i in range(count)])
    dek = crypto.decrypt_dek(wrapped)
    assert [crypto.decrypt(dek, values[f'h{i}'], ORG.encode()) for i in range(count)] == [f'synthetic-{i}' for i in range(count)]

async def test_interruption_during_preparation_and_retry(security_redis):
    vault, crypto, uc = await setup(security_redis)
    old = await vault.retrieve_dek(ORG)
    encrypt = crypto.encrypt
    calls = 0
    def crash(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('synthetic process interruption')
        return encrypt(*args, **kwargs)
    with patch.object(crypto, 'encrypt', side_effect=crash):
        with pytest.raises(RuntimeError):
            await uc.execute(ORG, 'retry')
    assert await vault.retrieve_dek(ORG) == old
    await assert_readable(vault, crypto)
    assert (await uc.execute(ORG, 'retry')).re_encrypted_count == 2
    await assert_readable(vault, crypto)

async def test_lost_ack_retry_is_idempotent_and_scoped(security_redis):
    vault, crypto, uc = await setup(security_redis)
    commit = vault.commit_rotation
    async def lost_ack(*args):
        await commit(*args)
        raise ConnectionError('synthetic lost reply after EXEC')
    with patch.object(vault, 'commit_rotation', side_effect=lost_ack):
        with pytest.raises(ConnectionError):
            await uc.execute(ORG, 'operation')
    committed = await vault.retrieve_dek(ORG)
    assert (await uc.execute(ORG, 'operation')).re_encrypted_count == 2
    assert await vault.retrieve_dek(ORG) == committed
    assert await vault.rotation_result(OTHER, 'operation') is None
    await assert_readable(vault, crypto)

async def test_disconnect_before_exec_no_mutations(security_redis):
    vault, crypto, uc = await setup(security_redis)
    old = await vault.retrieve_dek(ORG)
    with patch.object(vault, 'commit_rotation', side_effect=ConnectionError('before EXEC')):
        with pytest.raises(ConnectionError):
            await uc.execute(ORG, 'operation')
    assert await vault.retrieve_dek(ORG) == old
    assert await vault.rotation_result(ORG, 'operation') is None
    await assert_readable(vault, crypto)

async def test_new_token_after_scan_invalidates_snapshot(security_redis):
    vault, crypto, _ = await setup(security_redis)
    snapshot = await vault.snapshot_rotation(ORG)
    dek = crypto.decrypt_dek(snapshot.encrypted_dek)
    await vault.store(ORG, 'req', 'h2', crypto.encrypt(dek, 'synthetic-2', ORG.encode()), 60, expected_dek=snapshot.encrypted_dek)
    assert await vault.commit_rotation(ORG, snapshot, b'new', snapshot.tokens, 'operation') is None
    await assert_readable(vault, crypto, 3)

async def test_stale_writer_rejected_after_rotation(security_redis):
    vault, crypto, uc = await setup(security_redis)
    old = await vault.retrieve_dek(ORG)
    await uc.execute(ORG)
    assert await vault.store(ORG, 'req', 'late', b'oldct', 60, expected_dek=old) is False
    assert await vault.retrieve(ORG, 'req', 'late') is None
    await assert_readable(vault, crypto)

async def test_reader_snapshot_remains_valid_after_rotation(security_redis):
    vault, crypto, uc = await setup(security_redis)
    wrapped, values = await vault.retrieve_batch_with_dek(ORG, 'req', ['h0', 'h1'])
    await uc.execute(ORG)
    assert crypto.decrypt(crypto.decrypt_dek(wrapped), values['h0'], ORG.encode()) == 'synthetic-0'
    await assert_readable(vault, crypto)

async def test_ttl_not_extended_and_flush_not_resurrected(security_redis):
    vault, crypto, uc = await setup(security_redis)
    before = await security_redis.pttl(f'ps:{ORG}:req:h0')
    await uc.execute(ORG)
    assert 0 < await security_redis.pttl(f'ps:{ORG}:req:h0') <= before
    snapshot = await vault.snapshot_rotation(ORG)
    await vault.flush_request(ORG, 'req')
    assert await vault.commit_rotation(ORG, snapshot, snapshot.encrypted_dek, snapshot.tokens, 'flushed') == 0
    assert await vault.retrieve(ORG, 'req', 'h0') is None

async def test_unindexed_token_is_migrated(security_redis):
    vault, crypto, uc = await setup(security_redis)
    await security_redis.delete(f'ps:req:{ORG}:req')
    assert (await uc.execute(ORG)).re_encrypted_count == 2
    await assert_readable(vault, crypto)

async def test_corrupt_live_token_preserves_entire_old_state(security_redis):
    vault, crypto, uc = await setup(security_redis)
    old = await vault.retrieve_dek(ORG)
    first = await vault.retrieve(ORG, 'req', 'h0')
    await security_redis.set(f'ps:{ORG}:req:h1', b'corrupt', ex=60)
    with pytest.raises((InvalidTag, ValueError)):
        await uc.execute(ORG)
    assert await vault.retrieve_dek(ORG) == old
    assert await vault.retrieve(ORG, 'req', 'h0') == first

async def test_concurrent_rotations_and_tenant_isolation(security_redis):
    vault, crypto, uc = await setup(security_redis)
    other = await crypto.get_or_create_dek(OTHER)
    await vault.store(OTHER, 'req', 'other', crypto.encrypt(other, 'other', OTHER.encode()), 60)
    results = await asyncio.gather(*[uc.execute(ORG, 'same') for _ in range(8)])
    assert all(r.re_encrypted_count == 2 for r in results)
    assert crypto.decrypt_dek(await vault.retrieve_dek(OTHER)) == other
    await assert_readable(vault, crypto)

async def test_tokenize_retries_when_rotation_wins(security_redis):
    vault, crypto, uc = await setup(security_redis)
    store = vault.store
    calls = 0
    async def rotate_before_store(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            await uc.execute(ORG)
        return await store(*args, **kwargs)
    with patch.object(vault, 'store', side_effect=rotate_before_store):
        result = await TokenizeTextUseCase(RegexDetectionAdapter(), vault, crypto).execute('mail test@example.com', ORG, 'request')
    recovered = await RehydrateTextUseCase(vault, crypto).execute(result.tokenized_text, ORG, 'request')
    assert recovered.text == 'mail test@example.com' and calls >= 2

@pytest.mark.parametrize('ttl', [0, -1])
async def test_no_permanent_token_writes(security_redis, ttl):
    vault, _, _ = await setup(security_redis)
    with pytest.raises(ValueError):
        await vault.store(ORG, 'req', 'permanent', b'x', ttl)

async def test_no_ttl_token_aborts_rotation(security_redis):
    vault, crypto, uc = await setup(security_redis)
    old = await vault.retrieve_dek(ORG)
    await security_redis.persist(f'ps:{ORG}:req:h0')
    with pytest.raises(RuntimeError, match='no expiry'):
        await uc.execute(ORG)
    assert await vault.retrieve_dek(ORG) == old

async def test_expired_after_snapshot_not_resurrected(security_redis):
    vault, crypto, uc = await setup(security_redis)
    snapshot = await vault.snapshot_rotation(ORG)
    await security_redis.delete(f'ps:{ORG}:req:h0')
    new = b'y' * 32
    old = crypto.decrypt_dek(snapshot.encrypted_dek)
    rewritten = {pair: crypto.encrypt(new, crypto.decrypt(old, value, ORG.encode()), ORG.encode())
                 for pair, value in snapshot.tokens.items()}
    assert await vault.commit_rotation(ORG, snapshot, crypto.encrypt_dek(new), rewritten, 'expiry') == 1
    assert await vault.retrieve(ORG, 'req', 'h0') is None
    assert crypto.decrypt(new, await vault.retrieve(ORG, 'req', 'h1'), ORG.encode()) == 'synthetic-1'

async def test_disconnect_in_actual_transaction_before_exec(security_redis):
    vault, crypto, uc = await setup(security_redis)
    old = await vault.retrieve_dek(ORG)
    pipeline_type = type(security_redis.pipeline())
    with patch.object(pipeline_type, 'execute', side_effect=ConnectionError('before EXEC')):
        with pytest.raises(ConnectionError):
            await uc.execute(ORG, 'transaction')
    assert await vault.retrieve_dek(ORG) == old
    await assert_readable(vault, crypto)

async def test_disconnect_in_actual_transaction_after_exec(security_redis):
    vault, crypto, uc = await setup(security_redis)
    pipeline_type = type(security_redis.pipeline())
    execute = pipeline_type.execute
    async def lose_reply(pipe, *args, **kwargs):
        await execute(pipe, *args, **kwargs)
        raise ConnectionError('after EXEC')
    with patch.object(pipeline_type, 'execute', new=lose_reply):
        with pytest.raises(ConnectionError):
            await uc.execute(ORG, 'transaction')
    committed = await vault.retrieve_dek(ORG)
    assert (await uc.execute(ORG, 'transaction')).re_encrypted_count == 2
    assert await vault.retrieve_dek(ORG) == committed
    await assert_readable(vault, crypto)

async def test_distinct_concurrent_rotations_preserve_decryptability(security_redis):
    vault, crypto, uc = await setup(security_redis)
    results = await asyncio.gather(*[uc.execute(ORG, f'op-{i}') for i in range(4)], return_exceptions=True)
    assert any(not isinstance(result, Exception) for result in results)
    assert all(not isinstance(result, Exception) or isinstance(result, RuntimeError) for result in results)
    await assert_readable(vault, crypto)

async def test_oom_before_exec_preserves_old_state(security_redis):
    if hasattr(security_redis, 'server_type'):  # fakeredis doesn't enforce memory pressure
        return
    from fakeredis.aioredis import FakeRedis
    if isinstance(security_redis, FakeRedis):
        return
    from redis.exceptions import RedisError
    vault, crypto, uc = await setup(security_redis)
    old = await vault.retrieve_dek(ORG)
    await security_redis.config_set('maxmemory-policy', 'noeviction')
    await security_redis.config_set('maxmemory', 1)
    try:
        with pytest.raises(RedisError):
            await uc.execute(ORG, 'oom')
    finally:
        await security_redis.config_set('maxmemory', 0)
    assert await vault.retrieve_dek(ORG) == old
    assert await vault.rotation_result(ORG, 'oom') is None
    await assert_readable(vault, crypto)
