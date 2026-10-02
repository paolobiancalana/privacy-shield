"""Validate the actual Compose rendering; optional live OVH acceptance gate."""
import json
import os
from pathlib import Path
import subprocess
import pytest


def test_compose_memory_only_containers():
    env = dict(os.environ, PRIVACY_SHIELD_KEK_BASE64='eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=',
        REDIS_PASSWORD='synthetic', ADMIN_API_KEY='synthetic', SUPABASE_URL='', SUPABASE_SERVICE_KEY='')
    result = subprocess.run(['docker', 'compose', 'config', '--format', 'json'], env=env,
                            text=True, capture_output=True, check=True)
    services = json.loads(result.stdout)['services']
    for name in ['privacy-shield', 'redis']:
        service = services[name]
        assert service['read_only']
        assert service['ulimits']['core'].get('soft', 0) == 0
        assert service['ulimits']['core'].get('hard', 0) == 0
        memory = service.get('mem_limit') or service['deploy']['resources']['limits']['memory']
        assert service['memswap_limit'] == memory
        assert '/tmp' in service['tmpfs']
    redis_command = services['redis']['command']
    assert redis_command[redis_command.index('--save') + 1] == ''
    assert redis_command[redis_command.index('--appendonly') + 1] == 'no'
    assert redis_command[redis_command.index('--maxmemory-policy') + 1] == 'volatile-ttl'
    assert '/data' in services['redis']['tmpfs']


def test_hardening_script_syntax():
    subprocess.run(['bash', '-n', 'scripts/harden_pii_host.sh', 'scripts/check_pii_host.sh'], check=True)


@pytest.mark.skipif(not os.environ.get('PS_TEST_HOST'), reason='Set PS_TEST_HOST for read-only live infrastructure verification')
def test_live_host_memory_gate():
    result = subprocess.run(['ssh', os.environ['PS_TEST_HOST'], 'sudo bash -s'],
        input=Path('scripts/check_pii_host.sh').read_text(), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert 'PASS:' in result.stdout

@pytest.mark.skipif(not os.environ.get('PS_TEST_HOST'), reason='Set PS_TEST_HOST for live synthetic-body probe')
def test_live_nginx_large_synthetic_body_uses_only_tmpfs():
    # HTTP/1.1 chunked input exceeds client_body_buffer_size. No credentials,
    # customer data or successful operational request is used by this probe.
    probe = r'''
import http.client, json, subprocess
payload = json.dumps({'texts': ['SYNTHETIC_P0_BUFFER_CHECK_' * 8000],
 'organization_id': '11111111-1111-1111-1111-111111111111',
 'request_id': '22222222-2222-2222-2222-222222222222'}).encode()
conn = http.client.HTTPSConnection('api.privacyshield.pro', timeout=15)
conn.request('POST', '/api/v1/tokenize', body=iter([payload[i:i+4096] for i in range(0, len(payload), 4096)]),
 headers={'Content-Type': 'application/json'}, encode_chunked=True)
response = conn.getresponse()
assert response.status in (401, 413, 422), response.status
response.read()
for directory in ['/run/privacyshield-nginx/body', '/run/privacyshield-nginx/proxy']:
 result = subprocess.run(['findmnt', '-T', directory, '-no', 'FSTYPE'], capture_output=True, text=True, check=True)
 assert result.stdout.strip() == 'tmpfs'
print('PASS: chunked synthetic body; request and response temporary paths are tmpfs')
'''
    result = subprocess.run(['ssh', os.environ['PS_TEST_HOST'], 'sudo python3 -'],
                            input=probe, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert 'PASS:' in result.stdout
