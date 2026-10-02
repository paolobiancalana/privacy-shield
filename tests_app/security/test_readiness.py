import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.domain.entities import DetectionResult, PiiSpan
from app.infrastructure.api.routes import ready


def container():
    spans = [PiiSpan(10, 21, 'Mario Rossi', 'pe', 'slm', .85)]
    crypto = MagicMock()
    crypto.validate_kek.return_value = True
    return SimpleNamespace(redis_client=SimpleNamespace(ping=AsyncMock()), crypto_port=crypto,
        detection_port=SimpleNamespace(detect=AsyncMock(return_value=DetectionResult(spans, 1, 'slm'))),
        metrics=MagicMock(), config=SimpleNamespace(version='test'), _supabase_loader=None)


async def test_ready_requires_real_detection():
    c = container()
    result = await ready(c)
    assert result.status_code == 200
    assert json.loads(result.body)['components']['slm']['status'] == 'up'
    c.detection_port.detect.return_value = DetectionResult([], 1, 'slm')
    assert (await ready(c)).status_code == 503


@pytest.mark.parametrize('component', ['redis', 'ner', 'auth'])
async def test_component_failure_never_ready(component):
    c = container()
    if component == 'redis':
        c.redis_client.ping.side_effect = ConnectionError('synthetic')
    elif component == 'ner':
        c.detection_port.detect.side_effect = RuntimeError('synthetic')
    else:
        c._supabase_loader = SimpleNamespace(check_available=lambda: False)
    assert (await ready(c)).status_code == 503
