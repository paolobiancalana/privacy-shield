"""Deterministic post-processing for NER predicted spans.

Applies three sequential rules to improve entity boundary quality:
1. Trim external punctuation (protect abbreviations, apostrophes, parentheses)
2. Merge adjacent same-type entities (conservative gap rules per type)
3. Recalculate entity text from source offsets

This module does NOT:
- Change entity types
- Create new entities from nothing
- Perform any NER — it only refines spans already predicted
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Trim rules
# ---------------------------------------------------------------------------

# Punctuation to strip from END of entity span.
# NOTE: right single quote (\u2019) is NOT here — it's valid inside
# Italian names (D\u2019Amico) and gets special handling below.
_TRIM_TRAILING = set(",:;]}>?\u2014\u2013!")

# Punctuation to strip from START of entity span.
# NOTE: left single quote (\u2018) is NOT here — same reason.
_TRIM_LEADING = set("[{<")

# Trailing period is trimmed UNLESS it looks like an abbreviation.
# S.r.l.  S.p.a.  S.n.c.  dott.  ing.  avv.  geom.  prof.  ecc.
# The title/abbreviation list is explicit to avoid false matches
# (e.g. "Colombo." must NOT be protected — "ombo." is not an abbreviation).
_KNOWN_ABBREVS = frozenset({
    "dott.", "ing.", "avv.", "geom.", "prof.", "arch.", "rag.",
    "sig.", "sigg.", "spett.", "ecc.", "ecc..",
})
_ABBREV_TAIL_RE = re.compile(
    r"(?:"
    r"[A-Z](?:\.[a-zA-Z])+\.$"  # S.r.l. S.p.a. S.n.c.
    r")"
)

# English possessive suffix — only at the very end of a span
_POSSESSIVE_RE = re.compile(r"[a-zA-ZÀ-ÿ]['\u2019]s$")


def _trim_punctuation(
    start: int,
    end: int,
    source_text: str,
) -> tuple[int, int]:
    """Trim external punctuation from entity boundaries.

    Protections (will NOT trim):
    - Abbreviation-final periods: S.r.l., dott., ing.
    - Balanced parentheses: ) when ( exists in span
    - Internal apostrophes: D'Amico, L'Aquila (straight or curly)
    - Double quotes when they appear to wrap the entity symmetrically
    """
    # Trim leading
    while start < end:
        ch = source_text[start]
        if ch in _TRIM_LEADING:
            start += 1
        # Trim leading " or ( only if clearly external
        elif ch in "\"(" and (start == 0 or source_text[start - 1] in " \n\t"):
            start += 1
        else:
            break

    # Trim trailing — one character at a time, with guards
    while end > start:
        ch = source_text[end - 1]

        # Standard trailing punctuation
        if ch in _TRIM_TRAILING:
            # Protect balanced parentheses
            if ch == ")" and "(" in source_text[start:end - 1]:
                break
            end -= 1
            continue

        # Period: trim only if NOT part of an abbreviation
        if ch == ".":
            candidate = source_text[start:end]
            # Check structured abbreviations: S.r.l., S.p.a., etc.
            if _ABBREV_TAIL_RE.search(candidate):
                break
            # Check known title/word abbreviations: dott., ing., etc.
            # Extract the last word + period
            last_word_start = candidate.rfind(" ") + 1
            last_word = candidate[last_word_start:].lower()
            if last_word in _KNOWN_ABBREVS:
                break
            end -= 1
            continue

        # Right paren without matching left: trim
        if ch == ")" and "(" not in source_text[start:end - 1]:
            end -= 1
            continue

        # Possessive 's / \u2019s at end: trim the possessive suffix
        if ch == "s" and end - start >= 3:
            prev = source_text[end - 2]
            if prev in "'\u2019":
                # Only trim if preceded by a letter (actual possessive)
                if end - 3 >= start and source_text[end - 3].isalpha():
                    end -= 2  # remove 's
                    continue

        # Straight/curly quote at end: trim only if NOT preceded by letter
        # (protects D'Amico, L'Aquila, Caroli')
        if ch in "'\u2019":
            if end - 2 >= start and source_text[end - 2].isalpha():
                break  # internal apostrophe — protect
            end -= 1
            continue

        if ch == "\"":
            end -= 1
            continue

        break

    return start, end


# ---------------------------------------------------------------------------
# Merge rules
# ---------------------------------------------------------------------------

def _should_merge(
    a: dict,
    b: dict,
    source_text: str,
) -> bool:
    """Decide whether two adjacent same-type entities should merge.

    Conservative rules:
    - Same type required (caller already checks this)
    - Never merge across newlines
    - For 'ind': allow gap ≤ 2 chars if only whitespace and comma
    - For all other types: allow gap = exactly 1 space
    - Never merge if gap is empty (0 chars) — these are typically
      artifacts from trim and would create false merges
    """
    gap = source_text[a["e"]:b["s"]]

    # Never across newlines
    if "\n" in gap:
        return False

    # Never merge on zero-length gap (trim artifacts)
    if len(gap) == 0:
        return False

    entity_type = a["y"]

    if entity_type == "ind":
        # Addresses: allow merge across ", " or single space
        return len(gap) <= 2 and all(c in " ," for c in gap)

    # All other types: exactly one space
    return gap == " "


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fuse_spans(
    entities: list[dict],
    source_text: str,
) -> list[dict]:
    """Apply deterministic post-processing to predicted NER spans.

    Args:
        entities: List of entity dicts ``{"t", "y", "s", "e"}`` from
            NERInferenceEngine, sorted by start position.
        source_text: The original input text.

    Returns:
        Post-processed entity list (same format, potentially fewer entries).
    """
    if not entities:
        return []

    # Step 1: Trim punctuation on each entity
    trimmed: list[dict] = []
    for ent in entities:
        new_s, new_e = _trim_punctuation(ent["s"], ent["e"], source_text)

        if new_e <= new_s:
            continue  # trimmed to nothing — drop

        trimmed.append({
            "t": source_text[new_s:new_e],
            "y": ent["y"],
            "s": new_s,
            "e": new_e,
        })

    if not trimmed:
        return []

    # Step 2: Merge adjacent same-type entities
    merged: list[dict] = [trimmed[0]]

    for ent in trimmed[1:]:
        prev = merged[-1]

        if prev["y"] == ent["y"] and _should_merge(prev, ent, source_text):
            prev["e"] = ent["e"]
            prev["t"] = source_text[prev["s"]:prev["e"]]
        else:
            merged.append(ent)

    # Step 3: Final text recalculation (defensive)
    for ent in merged:
        ent["t"] = source_text[ent["s"]:ent["e"]]

    return merged
