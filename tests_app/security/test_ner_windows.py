from pathlib import Path
from unittest.mock import MagicMock
import numpy as np
import pytest
from app.infrastructure.adapters.ner_detection import NerDetectionAdapter
from app.infrastructure.adapters.composite_detection import CompositeDetectionAdapter
from app.infrastructure.adapters.regex_detection import RegexDetectionAdapter
from app.domain.services.span_fusion import fuse_spans

class Encoding(dict):
    def word_ids(self, batch_index=0):
        return [None if e == 0 else s for s, e in self['offset_mapping'][batch_index]]

class CharacterTokenizer:
    """Deterministic 1-char tokens to force many windows including Unicode."""
    def __call__(self, text, **kwargs):
        assert kwargs['return_overflowing_tokens'] and kwargs['stride'] > 0
        length = kwargs['max_length'] - 2
        step = length - kwargs['stride']
        starts = range(0, len(text), step)
        offsets, ids, masks = [], [], []
        for start in starts:
            end = min(len(text), start + length)
            pairs = [(0, 0)] + [(i, i + 1) for i in range(start, end)] + [(0, 0)]
            valid = len(pairs)
            pairs += [(0, 0)] * (length + 2 - valid)
            offsets.append(pairs)
            ids.append([s + 1 if e else 0 for s, e in pairs])
            masks.append([1] * valid + [0] * (length + 2 - valid))
            if end == len(text):
                break
        return Encoding(input_ids=np.array(ids), attention_mask=np.array(masks), offset_mapping=np.array(offsets))

@pytest.mark.parametrize('position', [0, 500, 505, 510, 511, 890, 2000, 9989])
async def test_every_window_and_boundary_global_unicode_offsets(position):
    name = 'Mario Rossi'
    text = 'à' * position + name + 'è' * max(0, 10000 - position - len(name))
    detector = object.__new__(NerDetectionAdapter)
    detector._tokenizer = CharacterTokenizer()
    def infer(_outputs, inputs):
        ids = inputs['input_ids'][0]
        logits = np.zeros((1, len(ids), 21))
        for i, token in enumerate(ids):
            char = token - 1
            label = 1 if char == position else 2 if position < char < position + len(name) else 0
            logits[0, i, label] = 1
        return [logits]
    detector._session = MagicMock()
    detector._session.run.side_effect = infer
    result = await detector.detect(text)
    spans = fuse_spans(result.spans)
    assert any(s.start == position and s.end == position + len(name) and s.text == name for s in spans)
    assert detector._session.run.call_count > 1
    assert all(s.text == text[s.start:s.end] for s in result.spans)

async def test_late_inference_failure_produces_no_partial_result():
    detector = object.__new__(NerDetectionAdapter)
    detector._tokenizer = CharacterTokenizer()
    detector._session = MagicMock()
    # Correct first-window model output, then failure in a later window.
    detector._session.run.side_effect = [[np.zeros((1, 512, 21))], RuntimeError('synthetic failure')]
    with pytest.raises(RuntimeError, match='synthetic failure'):
        await detector.detect('a' * 2000)

async def test_missing_tail_fails_closed():
    detector = object.__new__(NerDetectionAdapter)
    tokenize = CharacterTokenizer()
    def broken(text, **kwargs):
        result = tokenize(text, **kwargs)
        return Encoding({key: value[:1] for key, value in result.items()})
    detector._tokenizer = broken
    detector._session = MagicMock()
    detector._session.run.return_value = [np.zeros((1, 512, 21))]
    with pytest.raises(RuntimeError, match='coverage incomplete'):
        await detector.detect('a' * 1000)

@pytest.fixture(scope='module')
def actual_ner():
    model = Path('.local/pii-model/model_int8.onnx')
    if not model.exists():
        pytest.skip('Production-equivalent model absent; synthetic window tests still mandatory')
    return NerDetectionAdapter(str(model.parent))

@pytest.mark.parametrize('length', [0, 3500, 6390, 9950])
async def test_actual_model_detects_name_in_tail(actual_ner, length):
    prefix = ('testo generico senza informazioni. ' * 400)[:length]
    text = prefix + ' Il paziente si chiama Mario Rossi.'
    result = await CompositeDetectionAdapter(RegexDetectionAdapter(), actual_ner).detect(text)
    name_pos = text.index('Mario Rossi')
    assert any(s.start <= name_pos and s.end >= name_pos + 11 for s in result.spans)
    assert all(s.text == text[s.start:s.end] for s in result.spans)

async def test_actual_tokenizer_includes_last_window_and_overlap(actual_ner):
    text = ('à😀 testo generico senza informazioni. ' * 400)[:9900] + ' Mario Rossi'
    inputs = actual_ner._tokenizer(text, return_offsets_mapping=True,
        return_overflowing_tokens=True, max_length=512, stride=128, truncation=True,
        padding=True, return_tensors='np')
    assert len(inputs['input_ids']) > 1
    windows = [[(s, e) for s, e in window if e > s] for window in inputs['offset_mapping']]
    assert max(e for _, e in windows[-1]) == len(text)
    assert all(next_window[0][0] <= max(e for _, e in previous) for previous, next_window in zip(windows, windows[1:]))

@pytest.mark.parametrize('bad_output', [np.zeros((1, 10, 21)), np.zeros((1, 512, 20)), np.full((1, 512, 21), np.nan)])
async def test_invalid_inference_output_fails_closed(bad_output):
    detector = object.__new__(NerDetectionAdapter)
    detector._tokenizer = CharacterTokenizer()
    detector._session = MagicMock()
    detector._session.run.return_value = [bad_output]
    with pytest.raises(RuntimeError, match='Invalid NER inference'):
        await detector.detect('Mario Rossi')

async def test_actual_api_tail_tokenization_and_rehydration(actual_ner, monkeypatch):
    import base64
    monkeypatch.setenv("PRIVACY_SHIELD_KEK_BASE64", base64.b64encode(b"x" * 32).decode())
    import fakeredis.aioredis
    from app.main import create_app
    from app.container import Container
    from app.infrastructure.config import Settings
    from httpx import AsyncClient, ASGITransport
    settings = Settings(PRIVACY_SHIELD_KEK_BASE64=base64.b64encode(b'x' * 32).decode(),
                        SUPABASE_URL='', SUPABASE_SERVICE_KEY='', ADMIN_API_KEY='synthetic')
    app = create_app(settings)
    client_redis = fakeredis.aioredis.FakeRedis()
    container = Container(settings)
    container._redis = client_redis
    container._detection_adapter = CompositeDetectionAdapter(RegexDetectionAdapter(), actual_ner)
    app.state.container = container
    org = '11111111-1111-1111-1111-111111111111'
    req = '22222222-2222-2222-2222-222222222222'
    created = await container.create_api_key_use_case.execute(org)
    tail = 'Il signor Mario Rossi abita a Roma.'
    prefix = ('Questo documento contiene informazioni generali. ' * 210)[:10000 - len(tail) - 1] + ' '
    text = prefix + tail
    assert len(text) == 10000
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
            headers = {'X-Api-Key': created.raw_key}
            response = await client.post('/api/v1/tokenize', headers=headers,
                json={'texts': [text], 'organization_id': org, 'request_id': req})
            assert response.status_code == 200
            tokenized = response.json()['tokenized_texts'][0]
            assert 'Mario Rossi' not in tokenized
            response = await client.post('/api/v1/rehydrate', headers=headers,
                json={'text': tokenized, 'organization_id': org, 'request_id': req})
            assert response.status_code == 200 and response.json()['text'] == text
            response = await client.post('/api/v1/tokenize', headers=headers,
                json={'texts': ['x' * 10001], 'organization_id': org, 'request_id': req})
            assert response.status_code == 422
    finally:
        await client_redis.aclose()
