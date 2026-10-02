"""Run critical vault invariants against fake AND real Redis, never production."""
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
import fakeredis.aioredis
import pytest
import redis.asyncio as redis


@pytest.fixture(params=['fake', 'real'])
async def security_redis(request):
    process = None
    temp = None
    if request.param == 'fake':
        client = fakeredis.aioredis.FakeRedis()
    else:
        binary = shutil.which('redis-server')
        if not binary:
            pytest.fail('redis-server required for P0 acceptance suite')
        temp = tempfile.TemporaryDirectory(prefix='ps-p0-')
        socket = str(Path(temp.name) / 'redis.sock')
        process = subprocess.Popen([binary, '--port', '0', '--unixsocket', socket,
            '--unixsocketperm', '700', '--save', '', '--appendonly', 'no',
            '--dir', temp.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if Path(socket).exists():
                break
            time.sleep(.02)
        client = redis.Redis(unix_socket_path=socket)
        await client.ping()
    try:
        yield client
    finally:
        await client.aclose()
        if process:
            process.terminate()
            process.wait(timeout=5)
        if temp:
            temp.cleanup()
