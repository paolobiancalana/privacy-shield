# privacy-shield/app/domain/ports/detection_port.py
"""
DetectionPort — abstract contract for PII detection engines.

Implementors: RegexDetectionAdapter (Fase 1), SLMDetectionAdapter (Fase 2).
The domain layer depends only on this ABC; no concrete adapter is imported here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities import DetectionResult


class DetectionPort(ABC):
    """Detect PII spans within a raw text string."""

    @abstractmethod
    async def detect(self, text: str) -> DetectionResult:
        """
        Analyse 'text' and return all detected PII spans.

        Already-tokenized tokens ('[#tipo:xxxx]') MUST NOT be re-detected;
        implementations are responsible for filtering them out before matching.

        Args:
            text: Raw or partially-tokenized text to analyse.

        Returns:
            DetectionResult with discovered PiiSpan objects.
        """
        ...
