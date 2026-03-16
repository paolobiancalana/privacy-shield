"""
CompositeDetectionAdapter — combines Regex + NER detection.

Runs both detectors, merges results via span_fusion (regex wins on overlap).
Implements DetectionPort so it's a drop-in replacement in the container.
"""
from __future__ import annotations

import logging
import time

from app.domain.entities import DetectionResult, PiiSpan
from app.domain.ports.detection_port import DetectionPort
from app.domain.services.span_fusion import fuse_spans

logger = logging.getLogger("pii.composite_detection")


class CompositeDetectionAdapter(DetectionPort):
    """
    Composite detector: regex (high-precision patterns) + NER (contextual entities).

    The fusion layer ensures:
    - Regex wins on overlap (higher precision for structured patterns)
    - Adjacent same-type spans are merged
    - Output is sorted and non-overlapping
    """

    def __init__(self, regex: DetectionPort, ner: DetectionPort) -> None:
        self._regex = regex
        self._ner = ner

    async def detect(self, text: str) -> DetectionResult:
        t0 = time.perf_counter()

        # Run both detectors
        regex_result = await self._regex.detect(text)
        ner_result = await self._ner.detect(text)

        # Merge via span_fusion (handles overlap resolution + adjacent merge)
        all_spans = regex_result.spans + ner_result.spans
        fused = fuse_spans(all_spans)

        detection_ms = (time.perf_counter() - t0) * 1000.0

        logger.debug(
            "Composite detection: regex=%d, ner=%d, fused=%d (%.1fms)",
            len(regex_result.spans), len(ner_result.spans),
            len(fused), detection_ms,
        )

        return DetectionResult(
            spans=fused,
            detection_ms=detection_ms,
            source="composite",
        )
