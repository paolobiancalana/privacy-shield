"""Generate boundary-focused synthetic examples for NER retraining.

Targets specific failure modes:
- Multi-word person names with adjacent punctuation
- Complete Italian addresses (street, CAP, city, province)
- Entities adjacent to commas, periods, colons, parentheses, quotes
- Abbreviations (S.r.l., S.p.a., dott., ing.)
- Internal apostrophes (D'Amico, L'Aquila, dell'impresa)
- Balanced parentheses in entities ((CA), (PG))
- Hard negatives that look like PII but aren't
- Light OCR noise / spacing issues

Every example is validated deterministically at generation time:
text[start:end] == value — assertion failure = immediate crash.

Usage:
    python -m dataset.boundary_hard_generator
    python -m dataset.boundary_hard_generator --count 1000 --output-dir data/synthetic
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    label: str
    start: int
    end: int
    value: str


@dataclass
class Example:
    text: str
    entities: list[Entity] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "entities": [
                {
                    "text": e.value,
                    "type": e.label,
                    "start": e.start,
                    "end": e.end,
                }
                for e in self.entities
            ],
        }


def _make(text: str, entities: list[Entity]) -> Example:
    """Create example with deterministic offset validation."""
    for e in entities:
        actual = text[e.start:e.end]
        assert actual == e.value, (
            f"Offset mismatch: text[{e.start}:{e.end}]={actual!r} != {e.value!r}"
        )
    return Example(text=text, entities=entities)


# ── Name banks ────────────────────────────────────────────────────────

MALE = [
    "Marco", "Giuseppe", "Giovanni", "Antonio", "Francesco", "Mario",
    "Luigi", "Andrea", "Stefano", "Roberto", "Alessandro", "Luca",
    "Matteo", "Davide", "Paolo", "Federico", "Tommaso", "Leonardo",
]
FEMALE = [
    "Maria", "Anna", "Giulia", "Francesca", "Sara", "Laura",
    "Valentina", "Chiara", "Alessandra", "Federica", "Silvia", "Elena",
    "Martina", "Paola", "Sofia", "Beatrice", "Camilla", "Aurora",
]
SURNAMES = [
    "Rossi", "Russo", "Ferrari", "Esposito", "Bianchi", "Romano",
    "Colombo", "Ricci", "Marino", "Greco", "Bruno", "Gallo", "Conti",
    "De Luca", "Mancini", "Costa", "Giordano", "Rizzo", "Lombardi",
    "Moretti", "D'Amico", "D'Angelo", "Dell'Acqua",
]
APOSTROPHE_SURNAMES = ["D'Amico", "D'Angelo", "Dell'Acqua", "D'Alessio"]

STREETS = ["Via Roma", "Corso Garibaldi", "Piazza Dante", "Viale Mazzini",
           "Vicolo Stretto", "Largo San Giovanni", "Piazzale Michelangelo"]
CITIES = [
    ("Milano", "MI", "20100"), ("Roma", "RM", "00100"),
    ("Napoli", "NA", "80100"), ("Torino", "TO", "10100"),
    ("Firenze", "FI", "50100"), ("Bologna", "BO", "40100"),
    ("Genova", "GE", "16100"), ("Palermo", "PA", "90100"),
    ("Bari", "BA", "70100"), ("Cagliari", "CA", "09100"),
    ("Perugia", "PG", "06100"), ("Rimini", "RN", "47921"),
]
ORGS_ABBREV = [
    "Rossi S.r.l.", "Bianchi S.p.a.", "Ferrari S.n.c.",
    "Colombo & Figli S.r.l.", "Edilizia Moretti S.r.l.",
    "Termopoint S.r.l.", "Impianti Greco S.p.a.",
]
CONDITIONS = [
    "diabete di tipo 2", "ipertensione arteriosa", "asma bronchiale",
    "artrite reumatoide", "fibrillazione atriale", "celiachia",
]
APOSTROPHE_LOCS = ["L'Aquila", "L'Avana", "L'Aia"]


def _name(rng: random.Random) -> str:
    first = rng.choice(MALE + FEMALE)
    last = rng.choice(SURNAMES)
    return f"{first} {last}"


def _addr(rng: random.Random) -> str:
    street = rng.choice(STREETS)
    num = rng.randint(1, 200)
    city, prov, cap = rng.choice(CITIES)
    return f"{street} {num}, {cap} {city} ({prov})"


# ── Generators ────────────────────────────────────────────────────────

def _gen_person_punct(rng: random.Random, count: int) -> list[Example]:
    """Multi-word person with adjacent punctuation."""
    templates = [
        ("Gentile {name}, la informo che", ", la informo che"),
        ("Ho contattato {name}. Mi ha risposto", ". Mi ha risposto"),
        ("Chiedi a {name}: quando arriva?", ": quando arriva?"),
        ("Il sig. {name}, residente in", ", residente in"),
        ("{name}; ecco i documenti", "; ecco i documenti"),
        ("(contatto: {name})", ")"),
        ("\"{name}\" ha firmato il contratto", "\" ha firmato il contratto"),
    ]
    examples = []
    for _ in range(count):
        name = _name(rng)
        tmpl, suffix = rng.choice(templates)
        text = tmpl.replace("{name}", name)
        start = text.index(name)
        end = start + len(name)
        examples.append(_make(text, [Entity("pe", start, end, name)]))
    return examples


def _gen_person_apostrophe(rng: random.Random, count: int) -> list[Example]:
    """Person names with internal apostrophe."""
    prefixes = ["Il signor ", "La pratica di ", "Ho chiamato ", "Gentile "]
    suffixes = [" ieri", " stamattina", ", confermato", ". Grazie"]
    examples = []
    for _ in range(count):
        surname = rng.choice(APOSTROPHE_SURNAMES)
        first = rng.choice(MALE + FEMALE)
        name = f"{first} {surname}"
        prefix = rng.choice(prefixes)
        suffix = rng.choice(suffixes)
        text = f"{prefix}{name}{suffix}"
        start = len(prefix)
        end = start + len(name)
        examples.append(_make(text, [Entity("pe", start, end, name)]))
    return examples


def _gen_address_complete(rng: random.Random, count: int) -> list[Example]:
    """Full Italian address with CAP, city, province in parentheses."""
    prefixes = [
        "Residente in ", "Consegna a ", "Il cantiere è in ",
        "Sede legale: ", "Indirizzo di fatturazione: ",
    ]
    suffixes = [
        "", ".", ", Italia", " dal 2020",
    ]
    examples = []
    for _ in range(count):
        addr = _addr(rng)
        prefix = rng.choice(prefixes)
        suffix = rng.choice(suffixes)
        text = f"{prefix}{addr}{suffix}"
        start = len(prefix)
        end = start + len(addr)
        examples.append(_make(text, [Entity("ind", start, end, addr)]))
    return examples


def _gen_org_abbreviation(rng: random.Random, count: int) -> list[Example]:
    """Organization with abbreviation (S.r.l., S.p.a.) and adjacent punctuation."""
    templates = [
        ("Fattura di {org}, partita iva", ", partita iva"),
        ("La {org}. Con sede a", ". Con sede a"),
        ("Contratto con {org}: forniture", ": forniture"),
        ("({org})", ")"),
        ("Spett.le {org}, buongiorno", ", buongiorno"),
    ]
    examples = []
    for _ in range(count):
        org = rng.choice(ORGS_ABBREV)
        tmpl, suffix = rng.choice(templates)
        text = tmpl.replace("{org}", org)
        start = text.index(org)
        end = start + len(org)
        examples.append(_make(text, [Entity("org", start, end, org)]))
    return examples


def _gen_loc_apostrophe(rng: random.Random, count: int) -> list[Example]:
    """Locations with internal apostrophe."""
    prefixes = ["Sono di ", "Vive a ", "Proveniente da ", "Nato a "]
    suffixes = [", Italia", ".", ", una bella città", ""]
    examples = []
    for _ in range(count):
        loc = rng.choice(APOSTROPHE_LOCS)
        prefix = rng.choice(prefixes)
        suffix = rng.choice(suffixes)
        text = f"{prefix}{loc}{suffix}"
        start = len(prefix)
        end = start + len(loc)
        examples.append(_make(text, [Entity("loc", start, end, loc)]))
    return examples


def _gen_multi_entity(rng: random.Random, count: int) -> list[Example]:
    """Sentences with multiple entities of different types adjacent to punctuation."""
    examples = []
    for _ in range(count):
        name = _name(rng)
        addr = _addr(rng)
        condition = rng.choice(CONDITIONS)

        variant = rng.randint(0, 2)

        if variant == 0:
            # pe + ind: "Mario Rossi, residente in Via Roma 1, 20100 Milano (MI)."
            text = f"{name}, residente in {addr}."
            examples.append(_make(text, [
                Entity("pe", 0, len(name), name),
                Entity("ind", len(name) + len(", residente in "),
                       len(name) + len(", residente in ") + len(addr), addr),
            ]))
        elif variant == 1:
            # pe + org: "Fattura a Mario Rossi (Rossi S.r.l.)."
            org = rng.choice(ORGS_ABBREV)
            text = f"Fattura a {name} ({org})."
            name_start = len("Fattura a ")
            name_end = name_start + len(name)
            org_start = name_end + len(" (")
            org_end = org_start + len(org)
            examples.append(_make(text, [
                Entity("pe", name_start, name_end, name),
                Entity("org", org_start, org_end, org),
            ]))
        else:
            # pe + med: "Il paziente Mario Rossi soffre di diabete di tipo 2."
            text = f"Il paziente {name} soffre di {condition}."
            name_start = len("Il paziente ")
            name_end = name_start + len(name)
            cond_start = name_end + len(" soffre di ")
            cond_end = cond_start + len(condition)
            examples.append(_make(text, [
                Entity("pe", name_start, name_end, name),
                Entity("med", cond_start, cond_end, condition),
            ]))

    return examples


def _gen_hard_negatives(rng: random.Random, count: int) -> list[Example]:
    """Sentences that look like PII but aren't."""
    templates = [
        "Il codice prodotto è XR-4521-B per la caldaia.",
        "Riferimento ordine n. 2024/15832 del catalogo.",
        "Modello: Vaillant ecoTEC plus VMW 346/5-5.",
        "Numero di serie: SN-88432-IT-2025.",
        "Lotto di produzione LP-2024-0891.",
        "Il DDT n. 4521 del 15/03/2026 è confermato.",
        "Articolo 1655 del codice civile.",
        "Il preventivo n. 891/2026 è stato approvato.",
        "Temperatura di esercizio: 45-80°C.",
        "Scadenza garanzia: 24 mesi dalla data di installazione.",
        "La portata è di 14 litri al minuto.",
        "Classe energetica A++ secondo normativa UE 811/2013.",
        "Il rendimento stagionale è del 94%.",
        "Pressione massima di esercizio: 3 bar.",
        "Potenza termica nominale: 35 kW.",
    ]
    examples = []
    for _ in range(count):
        text = rng.choice(templates)
        examples.append(_make(text, []))
    return examples


def _gen_ocr_noise(rng: random.Random, count: int) -> list[Example]:
    """Entities with light OCR-like spacing/character noise."""
    examples = []
    for _ in range(count):
        name = _name(rng)
        addr = _addr(rng)

        variant = rng.randint(0, 2)
        if variant == 0:
            # Extra space in name
            text = f"Gentile  {name}, la informo"
            start = len("Gentile  ")
            end = start + len(name)
            examples.append(_make(text, [Entity("pe", start, end, name)]))
        elif variant == 1:
            # Tab before address
            text = f"Indirizzo:\t{addr}"
            start = len("Indirizzo:\t")
            end = start + len(addr)
            examples.append(_make(text, [Entity("ind", start, end, addr)]))
        else:
            # Newline in context
            text = f"Nome: {name}\nIndirizzo: {addr}"
            name_start = len("Nome: ")
            name_end = name_start + len(name)
            addr_start = name_end + len("\nIndirizzo: ")
            addr_end = addr_start + len(addr)
            examples.append(_make(text, [
                Entity("pe", name_start, name_end, name),
                Entity("ind", addr_start, addr_end, addr),
            ]))

    return examples


# ── Main ──────────────────────────────────────────────────────────────

def generate_boundary_hard(
    output_dir: Path,
    count: int = 1000,
    seed: int = 42,
) -> Path:
    """Generate boundary-hard synthetic pack."""
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Distribute count across generators
    alloc = {
        "person_punct": int(count * 0.20),
        "person_apostrophe": int(count * 0.08),
        "address_complete": int(count * 0.20),
        "org_abbreviation": int(count * 0.10),
        "loc_apostrophe": int(count * 0.05),
        "multi_entity": int(count * 0.15),
        "hard_negatives": int(count * 0.12),
        "ocr_noise": int(count * 0.10),
    }

    generators = {
        "person_punct": _gen_person_punct,
        "person_apostrophe": _gen_person_apostrophe,
        "address_complete": _gen_address_complete,
        "org_abbreviation": _gen_org_abbreviation,
        "loc_apostrophe": _gen_loc_apostrophe,
        "multi_entity": _gen_multi_entity,
        "hard_negatives": _gen_hard_negatives,
        "ocr_noise": _gen_ocr_noise,
    }

    all_examples: list[Example] = []
    entity_counter: Counter = Counter()

    for gen_name, gen_count in alloc.items():
        logger.info("Generating %d %s examples", gen_count, gen_name)
        examples = generators[gen_name](rng, gen_count)
        all_examples.extend(examples)
        for ex in examples:
            for ent in ex.entities:
                entity_counter[ent.label] += 1

    rng.shuffle(all_examples)

    output_path = output_dir / "boundary_hard.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in all_examples:
            f.write(json.dumps(ex.to_dict(), ensure_ascii=False) + "\n")

    print(f"\n{'=' * 60}")
    print("Boundary-Hard Synthetic Pack")
    print(f"  Total examples: {len(all_examples):,}")
    print(f"  Entity counts:")
    for etype, cnt in sorted(entity_counter.items()):
        print(f"    {etype:>5s}: {cnt:,}")
    print(f"  Output: {output_path}")
    print(f"{'=' * 60}\n")

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate boundary-focused synthetic examples."
    )
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--output-dir", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    generate_boundary_hard(args.output_dir, args.count, args.seed)


if __name__ == "__main__":
    main()
