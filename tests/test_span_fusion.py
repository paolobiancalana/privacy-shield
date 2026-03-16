"""Tests for inference/span_fusion.py edge cases.

Each test constructs a source_text and a list of predicted entities
(simulating NERInferenceEngine output), then verifies fuse_spans()
produces the expected result.
"""

from inference.span_fusion import fuse_spans


def _ent(text: str, etype: str, start: int, end: int) -> dict:
    return {"t": text, "y": etype, "s": start, "e": end}


# ── 1. Trim comma + merge multi-word person ──────────────────────────

def test_merge_person_trim_comma():
    """'Mario' pe + 'Rossi,' pe → 'Mario Rossi' pe"""
    source = "Senti Mario Rossi, dimmi quando arrivi"
    preds = [
        _ent("Mario", "pe", 6, 11),
        _ent("Rossi,", "pe", 12, 18),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 1
    assert result[0]["t"] == "Mario Rossi"
    assert result[0]["y"] == "pe"
    assert result[0]["s"] == 6
    assert result[0]["e"] == 17


# ── 2. Merge address + trim trailing period ──────────────────────────

def test_merge_address_trim_period():
    """Address parts merge across ', ' and trim final '.'"""
    source = "Abito in piazza Garibaldi 42, 47921 Rimini RN."
    preds = [
        _ent("piazza Garibaldi 42,", "ind", 9, 29),
        _ent("47921 Rimini RN.", "ind", 30, 46),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 1
    assert result[0]["t"] == "piazza Garibaldi 42, 47921 Rimini RN"
    assert result[0]["s"] == 9
    assert result[0]["e"] == 45


# ── 3. Protect S.r.l. abbreviation ──────────────────────────────────

def test_protect_srl_trim_comma():
    """'Rossi S.r.l.,' → trim comma, keep 'Rossi S.r.l.'"""
    source = "Fattura di Rossi S.r.l., partita iva 123"
    preds = [
        _ent("Rossi S.r.l.,", "org", 11, 24),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 1
    assert result[0]["t"] == "Rossi S.r.l."
    assert result[0]["e"] == 23


# ── 4. Protect internal apostrophe (D'Amico) ────────────────────────

def test_protect_apostrophe_damico():
    """D'Amico must not be broken by apostrophe handling."""
    source = "Il signor D'Amico ha chiamato"
    preds = [
        _ent("D'Amico", "pe", 10, 17),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 1
    assert result[0]["t"] == "D'Amico"


def test_protect_curly_apostrophe_laquila():
    """L\u2019Aquila with curly apostrophe must not be broken."""
    source = "Sono di L\u2019Aquila, una bella citt\u00e0"
    # L=8, '=9, A=10...a=15, ,=16  → entity with comma is 8:17
    preds = [
        _ent("L\u2019Aquila,", "loc", 8, 17),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 1
    assert result[0]["t"] == "L\u2019Aquila"
    assert result[0]["e"] == 16


# ── 5. Trim possessive 's without breaking name ─────────────────────

def test_trim_possessive():
    """Bakke's → Bakke (possessive trimmed)."""
    source = "According to Bakke's assessment"
    preds = [
        _ent("Bakke's", "pe", 13, 20),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 1
    assert result[0]["t"] == "Bakke"
    assert result[0]["e"] == 18


def test_no_trim_trailing_apostrophe_italian():
    """Caroli' (Italian name ending in apostrophe) must be preserved."""
    source = "Il paziente Caroli' è arrivato"
    preds = [
        _ent("Caroli'", "pe", 12, 19),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 1
    assert result[0]["t"] == "Caroli'"


# ── 6. Two separate persons — do NOT merge ───────────────────────────

def test_no_merge_separate_persons():
    """Two pe entities separated by non-space gap must not merge."""
    source = "Ho parlato con Mario, poi con Luca"
    preds = [
        _ent("Mario,", "pe", 15, 21),
        _ent("Luca", "pe", 30, 34),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 2
    assert result[0]["t"] == "Mario"
    assert result[1]["t"] == "Luca"


def test_no_merge_adjacent_persons_comma():
    """'Rossi,' pe + 'Bianchi' pe with gap ', ' must not merge (different people)."""
    source = "Presenti Rossi, Bianchi e altri"
    preds = [
        _ent("Rossi,", "pe", 9, 15),
        _ent("Bianchi", "pe", 16, 23),
    ]
    result = fuse_spans(preds, source)
    # After trim: "Rossi" (9:14) + "Bianchi" (16:23), gap = ", " = 2 chars
    # pe merge requires gap == " " (exactly 1 space), so these must NOT merge
    assert len(result) == 2
    assert result[0]["t"] == "Rossi"
    assert result[1]["t"] == "Bianchi"


# ── 7. Two distinct addresses — do NOT merge ─────────────────────────

def test_no_merge_distinct_addresses():
    """Two ind entities with large gap must not merge."""
    source = "Sede in Via Roma 1, consegna in Via Verdi 2"
    #         01234567890123456789012345678901234567890123
    #                 ^8       ^19           ^31     ^42
    preds = [
        _ent("Via Roma 1,", "ind", 8, 19),
        _ent("Via Verdi 2", "ind", 32, 43),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 2
    assert result[0]["t"] == "Via Roma 1"
    assert result[1]["t"] == "Via Verdi 2"


# ── 8. Preserve parentheses in address (CA), (PG) ───────────────────

def test_preserve_balanced_parentheses():
    """'Cagliari (CA)' must keep the parentheses."""
    source = "Il cantiere in Corso Roma 37, 09100 Cagliari (CA)"
    preds = [
        _ent("Corso Roma 37,", "ind", 15, 29),
        _ent("09100 Cagliari (CA)", "ind", 30, 49),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 1
    assert result[0]["t"] == "Corso Roma 37, 09100 Cagliari (CA)"
    assert result[0]["e"] == 49


def test_trim_unbalanced_paren():
    """Trailing ')' without matching '(' should be trimmed."""
    source = "il progetto di Roma) è stato approvato"
    preds = [
        _ent("Roma)", "loc", 15, 20),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 1
    assert result[0]["t"] == "Roma"
    assert result[0]["e"] == 19


# ── Extra: zero-gap merge prevention ─────────────────────────────────

def test_no_merge_zero_gap():
    """Entities with zero-length gap (touching) should not merge."""
    source = "MarioRossi è qui"
    preds = [
        _ent("Mario", "pe", 0, 5),
        _ent("Rossi", "pe", 5, 10),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 2


# ── Extra: empty after trim ──────────────────────────────────────────

def test_trim_trailing_period_on_name():
    """'Colombo.' must trim period — NOT an abbreviation."""
    source = "Marito: Luca Colombo."
    preds = [_ent("Luca Colombo.", "pe", 8, 21)]
    result = fuse_spans(preds, source)
    assert result[0]["t"] == "Luca Colombo"
    assert result[0]["e"] == 20


def test_protect_dott_abbreviation():
    """'Dott. Rossi' — period in 'Dott.' must be preserved."""
    source = "Il Dott. Rossi è qui"
    preds = [_ent("Dott.", "pro", 3, 8)]
    result = fuse_spans(preds, source)
    assert result[0]["t"] == "Dott."


def test_drop_entity_trimmed_to_empty():
    """Entity that becomes empty after trim is dropped."""
    source = "test ,. more text"
    preds = [
        _ent(",.", "pe", 5, 7),
    ]
    result = fuse_spans(preds, source)
    assert len(result) == 0
