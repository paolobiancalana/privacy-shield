"""End-to-end test harness for Privacy Shield PII detection.

Processes fixture files or individual texts through the full pipeline
(regex + NER + span_fusion) and reports extracted entities with timing.

Usage:
    python -m eval.e2e_test --model-path /content/ner_v2 --fixtures tests/fixtures/
    python -m eval.e2e_test --model-path /content/ner_v2 --text "Mario Rossi, CF RSSMRA85M01H501Z"
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("e2e_test")


# ── Regex PII engine (mirrors server RegexEntityExtractor patterns) ───

_REGEX_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("cf", re.compile(r"\b([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])\b")),
    ("ib", re.compile(r"\b(IT\d{2}[A-Z]\d{22})\b")),
    ("em", re.compile(r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b")),
    ("tel", re.compile(r"(?:\+39\s?)?(?:0\d{1,4}[\s\-]?\d{4,8}|3\d{2}[\s\-]?\d{6,7})\b")),
    ("piva", re.compile(r"\b(?:P\.?\s?IVA\s?)(\d{11})\b", re.IGNORECASE)),
    ("pec", re.compile(r"\b([a-zA-Z0-9._%+\-]+@pec\.[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b")),
    ("sdi", re.compile(r"\b(?:SDI|codice\s+sdi)\s+([A-Z0-9]{7})\b", re.IGNORECASE)),
]


def _extract_regex(text: str) -> list[dict]:
    """Run regex PII patterns on text."""
    entities = []
    for pii_type, pattern in _REGEX_PATTERNS:
        for match in pattern.finditer(text):
            group = match.group(1) if match.lastindex else match.group(0)
            start = match.start(1) if match.lastindex else match.start(0)
            end = match.end(1) if match.lastindex else match.end(0)
            entities.append({
                "t": group,
                "y": pii_type,
                "s": start,
                "e": end,
                "source": "regex",
            })
    return entities


def _merge_regex_ner(
    regex_entities: list[dict],
    ner_entities: list[dict],
) -> list[dict]:
    """Merge regex and NER entities. Regex wins on overlap."""
    # Build a set of character ranges covered by regex
    regex_ranges: set[int] = set()
    for ent in regex_entities:
        for i in range(ent["s"], ent["e"]):
            regex_ranges.add(i)

    # Keep NER entities that don't overlap with regex
    merged = list(regex_entities)
    for ent in ner_entities:
        ent_range = set(range(ent["s"], ent["e"]))
        overlap = ent_range & regex_ranges
        if len(overlap) / max(len(ent_range), 1) < 0.5:
            ent_with_source = {**ent, "source": "ner"}
            merged.append(ent_with_source)

    # Sort by start position
    merged.sort(key=lambda e: e["s"])
    return merged


def run_e2e(
    text: str,
    ner_engine,
    verbose: bool = False,
) -> dict:
    """Run full pipeline on a single text."""
    t0 = time.time()

    # Step 1: Regex
    t_regex = time.time()
    regex_ents = _extract_regex(text)
    regex_ms = (time.time() - t_regex) * 1000

    # Step 2: NER (includes span_fusion)
    t_ner = time.time()
    ner_ents = ner_engine.predict(text)
    ner_ms = (time.time() - t_ner) * 1000

    # Step 3: Merge
    t_merge = time.time()
    merged = _merge_regex_ner(regex_ents, ner_ents)
    merge_ms = (time.time() - t_merge) * 1000

    total_ms = (time.time() - t0) * 1000

    result = {
        "entities": merged,
        "counts": {
            "regex": len(regex_ents),
            "ner": len(ner_ents),
            "merged": len(merged),
            "collisions_dropped": len(regex_ents) + len(ner_ents) - len(merged),
        },
        "timing": {
            "regex_ms": round(regex_ms, 2),
            "ner_ms": round(ner_ms, 2),
            "merge_ms": round(merge_ms, 2),
            "total_ms": round(total_ms, 2),
        },
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="End-to-end PII detection test.")
    parser.add_argument("--model-path", type=str, required=True)
    parser.add_argument("--fixtures", type=str, default=None, help="Directory with fixture JSONL files")
    parser.add_argument("--text", type=str, default=None, help="Single text to process")
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    from inference.inference import NERInferenceEngine
    engine = NERInferenceEngine(args.model_path, device=args.device, use_span_fusion=True)

    results = []

    if args.text:
        r = run_e2e(args.text, engine, verbose=True)
        _print_result("CLI input", args.text, r)
        results.append({"id": "cli", "text": args.text, **r})

    if args.fixtures:
        fixtures_dir = Path(args.fixtures)
        for fp in sorted(fixtures_dir.glob("*.jsonl")):
            with open(fp) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    text = obj.get("text", "")
                    doc_id = obj.get("id", "unknown")

                    r = run_e2e(text, engine)
                    _print_result(doc_id, text, r)
                    results.append({"id": doc_id, "text": text[:200], **r})

    # Summary
    if results:
        total_regex = sum(r["counts"]["regex"] for r in results)
        total_ner = sum(r["counts"]["ner"] for r in results)
        total_merged = sum(r["counts"]["merged"] for r in results)
        avg_time = sum(r["timing"]["total_ms"] for r in results) / len(results)

        print(f"\n{'=' * 70}")
        print("E2E Test Summary")
        print(f"  Documents: {len(results)}")
        print(f"  Total regex spans: {total_regex}")
        print(f"  Total NER spans: {total_ner}")
        print(f"  Total merged spans: {total_merged}")
        print(f"  Avg time/doc: {avg_time:.1f} ms")
        print(f"{'=' * 70}")

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        logger.info("Results saved to %s", out)


def _print_result(doc_id: str, text: str, r: dict) -> None:
    """Print a single document result."""
    print(f"\n{'─' * 70}")
    print(f"  [{doc_id}] {text[:100]}{'...' if len(text) > 100 else ''}")
    print(f"  Timing: regex={r['timing']['regex_ms']:.1f}ms, ner={r['timing']['ner_ms']:.1f}ms, "
          f"total={r['timing']['total_ms']:.1f}ms")
    print(f"  Spans: regex={r['counts']['regex']}, ner={r['counts']['ner']}, "
          f"merged={r['counts']['merged']}, dropped={r['counts']['collisions_dropped']}")

    for ent in r["entities"]:
        src = ent.get("source", "?")
        print(f"    [{src:>5s}] [{ent['y']:>5s}] \"{ent['t']}\"  ({ent['s']}:{ent['e']})")

    warnings = []
    if r["counts"]["collisions_dropped"] > 0:
        warnings.append(f"{r['counts']['collisions_dropped']} NER spans dropped (regex overlap)")
    if not r["entities"]:
        warnings.append("No entities found")
    for w in warnings:
        print(f"    ⚠ {w}")


if __name__ == "__main__":
    main()
