import json
import logging
import sys
from app.infrastructure.telemetry import _JsonFormatter


def test_exception_message_cause_traceback_and_interpolated_message_not_logged():
    marker = 'SYNTHETIC_PRIVATE_CONTENT'
    try:
        try:
            raise ValueError(marker)
        except ValueError as exc:
            raise RuntimeError(marker) from exc
    except RuntimeError:
        record = logging.LogRecord('service', logging.ERROR, __file__, 1,
                                   'failure: %s', (marker,), sys.exc_info())
        record._ps_error_code = 'SYNTHETIC_FAILURE'
        rendered = _JsonFormatter().format(record)
    payload = json.loads(rendered)
    assert marker not in rendered
    assert 'exception' not in payload
    assert payload['exception_type'] == 'RuntimeError'
    assert payload['error_code'] == 'SYNTHETIC_FAILURE'
