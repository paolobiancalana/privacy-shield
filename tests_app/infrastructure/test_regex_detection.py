"""
RegexDetectionAdapter tests — Italian PII pattern coverage.

Adversarial Analysis:
  1. Existing tokens [#pe:xxxx] could be re-detected if masking fails.
  2. IBAN regex must be case-insensitive (lowercase IT prefix valid in user input).
  3. P.IVA 11-digit pattern has high false-positive risk -- verify confidence < 1.0.
"""
from __future__ import annotations

import pytest

from app.domain.entities import DetectionResult
from app.infrastructure.adapters.regex_detection import RegexDetectionAdapter


@pytest.fixture
def detector() -> RegexDetectionAdapter:
    return RegexDetectionAdapter()


class TestCodiceFiscale:
    """CF: 16-char alphanumeric Italian tax code."""

    async def test_valid_cf_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("Il codice fiscale e' RSSMRA85M01H501Z ciao")
        cf_spans = [s for s in result.spans if s.pii_type == "cf"]
        assert len(cf_spans) == 1
        assert cf_spans[0].text == "RSSMRA85M01H501Z"
        assert cf_spans[0].confidence == 1.0

    async def test_lowercase_cf_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("cf rssmra85m01h501z qui")
        cf_spans = [s for s in result.spans if s.pii_type == "cf"]
        assert len(cf_spans) == 1

    async def test_invalid_cf_not_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("Il codice INVALID123456 non e' valido")
        cf_spans = [s for s in result.spans if s.pii_type == "cf"]
        assert len(cf_spans) == 0


class TestIban:
    """IBAN: IT prefix + 2 check + 1 letter + 22 digits."""

    async def test_valid_iban_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("IBAN: IT60X0542811101000000123456")
        ib_spans = [s for s in result.spans if s.pii_type == "ib"]
        assert len(ib_spans) == 1
        assert ib_spans[0].text == "IT60X0542811101000000123456"
        assert ib_spans[0].confidence == 1.0

    async def test_lowercase_iban_detected(self, detector: RegexDetectionAdapter) -> None:
        """Case-insensitive matching for user-typed IBANs."""
        result = await detector.detect("iban: it60x0542811101000000123456")
        ib_spans = [s for s in result.spans if s.pii_type == "ib"]
        assert len(ib_spans) == 1


class TestEmail:
    """Email: standard RFC-5322 subset."""

    async def test_email_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("Scrivi a mario.rossi@example.com per info")
        em_spans = [s for s in result.spans if s.pii_type == "em"]
        assert len(em_spans) == 1
        assert em_spans[0].text == "mario.rossi@example.com"
        assert em_spans[0].confidence == 1.0


class TestPhone:
    """Phone: Italian mobile + fixed-line with optional +39 prefix."""

    async def test_phone_with_prefix_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("Chiama +39 333 1234567 subito")
        tel_spans = [s for s in result.spans if s.pii_type == "tel"]
        assert len(tel_spans) == 1
        assert tel_spans[0].confidence == 0.85

    async def test_phone_without_prefix_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("Chiama 333 1234567 subito")
        tel_spans = [s for s in result.spans if s.pii_type == "tel"]
        assert len(tel_spans) >= 1

    async def test_fixed_line_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("Tel ufficio 02 12345678")
        tel_spans = [s for s in result.spans if s.pii_type == "tel"]
        assert len(tel_spans) >= 1


class TestDate:
    """Date: dd/mm/yyyy Italian format."""

    async def test_date_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("Nato il 01/01/1990 a Roma")
        dt_spans = [s for s in result.spans if s.pii_type == "dt"]
        assert len(dt_spans) == 1
        assert dt_spans[0].text == "01/01/1990"
        assert dt_spans[0].confidence == 0.90

    async def test_date_with_dots_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("Data: 15.06.2000")
        dt_spans = [s for s in result.spans if s.pii_type == "dt"]
        assert len(dt_spans) == 1


class TestPartitaIva:
    """P.IVA: 11 consecutive digits, lower confidence due to false-positive risk."""

    async def test_piva_starting_with_zero_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("P.IVA 01234567890 della ditta")
        fin_spans = [s for s in result.spans if s.pii_type == "fin"]
        assert len(fin_spans) == 1
        assert fin_spans[0].confidence == 0.80

    async def test_piva_not_starting_with_zero_detected(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("P.IVA 12345678901 della ditta")
        fin_spans = [s for s in result.spans if s.pii_type == "fin"]
        assert len(fin_spans) == 1
        assert fin_spans[0].confidence == 0.65


class TestMultiplePiiInOneText:
    """Multiple PII types in a single text."""

    async def test_multiple_types_detected(self, detector: RegexDetectionAdapter) -> None:
        text = "Mario (RSSMRA85M01H501Z) email mario@test.com tel +39 333 1234567"
        result = await detector.detect(text)
        types_found = {s.pii_type for s in result.spans}
        assert "cf" in types_found
        assert "em" in types_found
        assert "tel" in types_found


class TestIdempotencyExistingTokens:
    """Existing tokens [#tipo:xxxx] must NOT be re-detected."""

    async def test_existing_token_not_re_detected(self, detector: RegexDetectionAdapter) -> None:
        text = "Ciao [#pe:a3f2] come stai"
        result = await detector.detect(text)
        # No spans should overlap with the token position
        token_start = text.index("[#pe:a3f2]")
        token_end = token_start + len("[#pe:a3f2]")
        for span in result.spans:
            assert not (span.start < token_end and token_start < span.end), (
                f"Span {span.text!r} at [{span.start}:{span.end}) overlaps existing token"
            )

    async def test_pii_after_token_still_detected(self, detector: RegexDetectionAdapter) -> None:
        text = "[#pe:a3f2] chiama mario.rossi@test.com"
        result = await detector.detect(text)
        em_spans = [s for s in result.spans if s.pii_type == "em"]
        assert len(em_spans) == 1


class TestEmptyAndNoPii:
    """Edge cases: empty text, no PII."""

    async def test_empty_text_empty_result(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("")
        assert result.spans == []
        assert result.source == "regex"

    async def test_text_without_pii(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("Buongiorno, come posso aiutarti oggi?")
        assert result.spans == []

    async def test_detection_result_has_timing(self, detector: RegexDetectionAdapter) -> None:
        result = await detector.detect("test")
        assert result.detection_ms >= 0.0
