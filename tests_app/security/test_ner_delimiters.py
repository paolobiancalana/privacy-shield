from pathlib import Path

import pytest

from app.infrastructure.adapters.ner_detection import NerDetectionAdapter


@pytest.fixture(scope='module')
def detector():
    model = Path('.local/pii-model/model_int8.onnx')
    if not model.exists():
        pytest.skip('Real model required for delimiter acceptance')
    return NerDetectionAdapter(str(model.parent))


async def test_quoted_full_name_preserves_exact_boundaries(detector):
    result = await detector.detect('fullName = "Mario Rossi"')
    assert [(s.start, s.end, s.text, s.pii_type) for s in result.spans] == [
        (12, 23, 'Mario Rossi', 'pe')
    ]


async def test_quoted_java_name_excludes_closing_quote_and_semicolon(detector):
    result = await detector.detect('String name = "Mario Rossi";')
    assert [(s.start, s.end, s.text, s.pii_type) for s in result.spans] == [
        (15, 26, 'Mario Rossi', 'pe')
    ]


async def test_single_quoted_name_excludes_string_delimiters(detector):
    result = await detector.detect("name = 'Mario Rossi'")
    assert [(s.start, s.end, s.text, s.pii_type) for s in result.spans] == [
        (8, 19, 'Mario Rossi', 'pe')
    ]


@pytest.mark.parametrize('text', [
    'const cityField = "city";',
    'String cityField = "city";',
    'className = "PersonService"',
])
async def test_non_person_strings_are_not_promoted_to_entities(detector, text):
    assert (await detector.detect(text)).spans == []


@pytest.mark.parametrize('text,name', [
    ('Il signor Mario Rossi abita qui.', 'Mario Rossi'),
    ('Il signor Marco D\'Angelo abita qui.', "Marco D'Angelo"),
    ('Il signor Jean-Pierre Dupont abita qui.', 'Jean-Pierre Dupont'),
])
async def test_prose_names_keep_internal_punctuation(detector, text, name):
    result = await detector.detect(text)
    assert any(s.text == name and s.pii_type == 'pe' for s in result.spans)
    assert all(s.text == text[s.start:s.end] for s in result.spans)
