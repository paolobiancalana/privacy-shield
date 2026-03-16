"""Clean and filter mixed training data for Privacy Shield.

Loads JSONL files from data/processed/ and data/synthetic/, applies a set of
quality filters, and writes cleaned output to data/cleaned/.

Filters applied
---------------
pe  – Remove entities whose text matches a code/ID pattern (digits+letters,
      e.g. "2016NF", "AB123").  Person names should not look like identifiers.

ind – Remove entities whose text is a bare short number (< 5 chars, all digits).
      A house number alone is not an address.

dt  – Remove entities whose text matches an ISO or structured date format
      (YYYY-MM-DD or DD/MM/YYYY).  These are handled by the regex engine and
      must not appear in SLM training data.

med – Remove entities whose text contains hospital/clinic keywords
      ("ospedale", "clinica", "asl", "policlinico", "pronto soccorso").
      Facility names should be tagged org, not med.

org – Flag (log but do NOT remove) org entities that are a single word and
      match a known Italian city pattern.  These might be mis-tagged loc entities.

Usage
-----
    python -m dataset.clean_mix
    python -m dataset.clean_mix --processed-dir data/processed --synthetic-dir data/synthetic --output-dir data/cleaned
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled filter patterns
# ---------------------------------------------------------------------------

# pe: text looks like an alphanumeric code (contains both digits and letters,
# no spaces, 3–12 chars).  Examples: "2016NF", "AB12C", "XF99Z".
_PE_CODE_RE = re.compile(r"^(?=.*\d)(?=.*[a-zA-Z])[a-zA-Z0-9]{3,12}$")

# dt: ISO date (YYYY-MM-DD) or structured Italian date (DD/MM/YYYY).
_DT_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DT_SLASH_RE = re.compile(r"\d{2}/\d{2}/\d{4}")

# med: hospital / clinic indicator keywords (case-insensitive).
_MED_FACILITY_RE = re.compile(
    r"\b(ospedale|clinica|asl|policlinico|pronto\s+soccorso|istituto\s+ortopedico)\b",
    re.IGNORECASE,
)

# org: single-word entity that could be an Italian city.
# This is a heuristic: a single capitalised word ≥ 4 chars with no digits.
_ORG_CITY_LIKE_RE = re.compile(r"^[A-ZÀÈÉÌÒÙ][a-zàèéìòùA-ZÀÈÉÌÒÙ]{3,}$")

# Known major Italian cities (lower-case for comparison) — not exhaustive but
# covers the most frequent false positives.
_KNOWN_CITIES: frozenset[str] = frozenset({
    "milano", "roma", "napoli", "torino", "firenze", "bologna", "genova",
    "palermo", "bari", "catania", "venezia", "verona", "padova", "trieste",
    "brescia", "bergamo", "modena", "parma", "perugia", "cagliari", "livorno",
    "ravenna", "rimini", "salerno", "pisa", "lecce", "ancona", "pescara",
    "como", "reggio", "messina", "vicenza", "trento", "siena", "treviso",
    "monza", "foggia", "ferrara", "sassari", "latina", "giugliano", "reggio emilia",
})


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------


def _should_remove_pe(entity_text: str) -> bool:
    """Return True if a pe entity looks like an identifier/code."""
    return bool(_PE_CODE_RE.match(entity_text.strip()))


def _should_remove_ind(entity_text: str) -> bool:
    """Return True if an ind entity is a bare short number."""
    stripped = entity_text.strip()
    return len(stripped) < 5 and stripped.isdigit()


def _should_remove_dt(entity_text: str) -> bool:
    """Return True if a dt entity is in a structured date format (regex territory)."""
    text = entity_text.strip()
    return bool(_DT_ISO_RE.search(text) or _DT_SLASH_RE.search(text))


def _should_remove_med(entity_text: str) -> bool:
    """Return True if a med entity is a hospital/clinic name rather than a condition."""
    return bool(_MED_FACILITY_RE.search(entity_text))


def _is_org_city_like(entity_text: str) -> bool:
    """Return True if an org entity looks like a city name (flag only, no removal)."""
    text = entity_text.strip()
    # Single-word check
    if " " in text:
        return False
    if not _ORG_CITY_LIKE_RE.match(text):
        return False
    return text.lower() in _KNOWN_CITIES


# ---------------------------------------------------------------------------
# Core cleaning logic
# ---------------------------------------------------------------------------


def _filter_entities(
    entities: list[dict],
    removed_counter: Counter,
    flagged_counter: Counter,
    source: str,
) -> list[dict]:
    """Apply per-type filters to an entity list.

    Args:
        entities:        Raw entity dicts from a JSONL record.
        removed_counter: Accumulates removal counts per filter name.
        flagged_counter: Accumulates flag counts per filter name.
        source:          Source identifier for log messages.

    Returns:
        Filtered entity list (flagged entities are kept but logged).
    """
    kept: list[dict] = []

    for ent in entities:
        etype = ent.get("type", "")
        etext = ent.get("text", "")

        if etype == "pe" and _should_remove_pe(etext):
            logger.debug("[%s] Removing pe code/ID: %r", source, etext)
            removed_counter["pe_code_id"] += 1
            continue

        if etype == "ind" and _should_remove_ind(etext):
            logger.debug("[%s] Removing ind bare number: %r", source, etext)
            removed_counter["ind_bare_number"] += 1
            continue

        if etype == "dt" and _should_remove_dt(etext):
            logger.debug("[%s] Removing dt structured date: %r", source, etext)
            removed_counter["dt_structured_date"] += 1
            continue

        if etype == "med" and _should_remove_med(etext):
            logger.debug("[%s] Removing med facility name: %r", source, etext)
            removed_counter["med_facility_name"] += 1
            continue

        if etype == "org" and _is_org_city_like(etext):
            logger.warning(
                "[%s] Flagged org looks like city: %r — kept, but review recommended",
                source,
                etext,
            )
            flagged_counter["org_city_like"] += 1
            # Do NOT remove — only flag

        kept.append(ent)

    return kept


def _load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file, skipping malformed lines."""
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed JSON at %s:%d — %s", path.name, lineno, exc)
    return records


def _collect_jsonl_files(*dirs: Path) -> list[tuple[Path, str]]:
    """Return (path, source_label) pairs for all .jsonl files under given dirs."""
    result: list[tuple[Path, str]] = []
    for base in dirs:
        if not base.exists():
            logger.info("Directory does not exist, skipping: %s", base)
            continue
        for fp in sorted(base.rglob("*.jsonl")):
            result.append((fp, fp.stem))
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def clean_mix(
    processed_dir: Path,
    synthetic_dir: Path,
    output_dir: Path,
) -> None:
    """Load, clean, and save mixed training data.

    Args:
        processed_dir: Directory containing processed JSONL files.
        synthetic_dir: Directory containing synthetic JSONL files.
        output_dir:    Destination directory for cleaned output files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    files = _collect_jsonl_files(processed_dir, synthetic_dir)
    if not files:
        logger.error(
            "No .jsonl files found under %s or %s — nothing to clean.",
            processed_dir,
            synthetic_dir,
        )
        return

    total_records_in = 0
    total_records_out = 0
    total_entities_in = 0
    total_entities_out = 0
    global_removed: Counter = Counter()
    global_flagged: Counter = Counter()

    for src_path, source_label in files:
        records = _load_jsonl(src_path)
        if not records:
            logger.info("Empty file, skipping: %s", src_path)
            continue

        cleaned_records: list[dict] = []
        file_removed: Counter = Counter()
        file_flagged: Counter = Counter()
        file_entities_in = 0
        file_entities_out = 0

        for record in records:
            entities_in = record.get("entities", [])
            file_entities_in += len(entities_in)

            entities_out = _filter_entities(
                entities_in, file_removed, file_flagged, source_label,
            )
            file_entities_out += len(entities_out)

            # Build cleaned record, preserving all original keys
            cleaned = {**record, "entities": entities_out}
            cleaned_records.append(cleaned)

        # Decide output filename: mirror source relative path under output_dir
        # For simplicity, flatten to a single level using the stem.
        out_path = output_dir / src_path.name
        if out_path.exists():
            # Avoid collisions if both source dirs have a file with the same name
            out_path = output_dir / f"{source_label}_{src_path.parent.name}.jsonl"

        with out_path.open("w", encoding="utf-8") as fh:
            for rec in cleaned_records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # Accumulate globals
        total_records_in += len(records)
        total_records_out += len(cleaned_records)  # same — we never drop whole records
        total_entities_in += file_entities_in
        total_entities_out += file_entities_out
        global_removed.update(file_removed)
        global_flagged.update(file_flagged)

        # Per-file report
        removed_total = sum(file_removed.values())
        flagged_total = sum(file_flagged.values())
        logger.info(
            "%-40s  records=%d  ent_in=%d  ent_out=%d  removed=%d  flagged=%d",
            src_path.name,
            len(records),
            file_entities_in,
            file_entities_out,
            removed_total,
            flagged_total,
        )

    # Final summary
    print(f"\n{'=' * 70}")
    print("Privacy Shield — Dataset Cleaning Report")
    print(f"{'=' * 70}")
    print(f"  Source files processed : {len(files)}")
    print(f"  Total records          : {total_records_in:,}")
    print(f"  Total entities (in)    : {total_entities_in:,}")
    print(f"  Total entities (out)   : {total_entities_out:,}")
    print(f"  Total entities removed : {total_entities_in - total_entities_out:,}")
    print()
    print("  Removed by filter:")
    for filter_name, count in sorted(global_removed.items()):
        print(f"    {filter_name:<30s}: {count:,}")
    if not global_removed:
        print("    (none)")
    print()
    print("  Flagged (kept, review recommended):")
    for filter_name, count in sorted(global_flagged.items()):
        print(f"    {filter_name:<30s}: {count:,}")
    if not global_flagged:
        print("    (none)")
    print(f"\n  Output written to: {output_dir.resolve()}")
    print(f"{'=' * 70}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Clean and filter Privacy Shield training data from processed/ and synthetic/."
        )
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory containing processed JSONL files (default: data/processed)",
    )
    parser.add_argument(
        "--synthetic-dir",
        type=Path,
        default=Path("data/synthetic"),
        help="Directory containing synthetic JSONL files (default: data/synthetic)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/cleaned"),
        help="Output directory for cleaned JSONL files (default: data/cleaned)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging (shows every removed entity)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    clean_mix(args.processed_dir, args.synthetic_dir, args.output_dir)


if __name__ == "__main__":
    main()
