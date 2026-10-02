"""Unit contract: prepare everything first; one commit; no skipped corrupt data."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.application.rotate_dek import RotateDekUseCase
from app.domain.ports.vault_port import RotationSnapshot


@pytest.fixture
def ports():
    vault = AsyncMock()
    vault.rotation_result.return_value = None
    vault.snapshot_rotation.return_value = RotationSnapshot(b'old', b'rev', {('req', 'h'): b'ct'})
    vault.commit_rotation.return_value = 1
    crypto = MagicMock()
    crypto.decrypt_dek.return_value = b'x' * 32
    crypto.decrypt.return_value = 'synthetic'
    crypto.encrypt.return_value = b'newct'
    crypto.encrypt_dek.return_value = b'newdek'
    return vault, crypto, RotateDekUseCase(vault, crypto)


async def test_prepare_then_single_atomic_commit(ports):
    vault, crypto, uc = ports
    result = await uc.execute('org', 'operation')
    assert result.re_encrypted_count == 1
    args = vault.commit_rotation.call_args.args
    assert args[3] == {('req', 'h'): b'newct'} and args[4] == 'operation'
    vault.store.assert_not_called()
    vault.store_dek.assert_not_called()
    crypto.decrypt.assert_called_once_with(b'x' * 32, b'ct', associated_data=b'org')


async def test_committed_retry_does_not_generate_or_encrypt(ports):
    vault, crypto, uc = ports
    vault.rotation_result.return_value = 7
    assert (await uc.execute('org', 'operation')).re_encrypted_count == 7
    vault.snapshot_rotation.assert_not_called()
    crypto.encrypt.assert_not_called()


async def test_no_dek_no_writes(ports):
    vault, _, uc = ports
    vault.snapshot_rotation.return_value = RotationSnapshot(None, None, {})
    with pytest.raises(ValueError, match='No DEK'):
        await uc.execute('org')
    vault.commit_rotation.assert_not_called()


@pytest.mark.parametrize('failure', [RuntimeError('corrupt'), ValueError('invalid')])
async def test_any_corrupt_token_aborts_entire_rotation(ports, failure):
    vault, crypto, uc = ports
    vault.snapshot_rotation.return_value = RotationSnapshot(b'old', b'rev', {('r', 'a'): b'a', ('r', 'b'): b'b'})
    crypto.decrypt.side_effect = ['synthetic', failure]
    with pytest.raises(type(failure)):
        await uc.execute('org')
    vault.commit_rotation.assert_not_called()


async def test_contention_rebuilds_from_fresh_snapshot(ports):
    vault, _, uc = ports
    vault.commit_rotation.side_effect = [None, 1]
    assert (await uc.execute('org')).re_encrypted_count == 1
    assert vault.snapshot_rotation.call_count == 2


async def test_contention_is_bounded_and_fails_closed(ports):
    vault, _, uc = ports
    vault.commit_rotation.return_value = None
    with pytest.raises(RuntimeError, match='contention'):
        await uc.execute('org', 'same-operation')
    assert vault.commit_rotation.call_count == 5
    assert all(c.args[4] == 'same-operation' for c in vault.commit_rotation.call_args_list)
