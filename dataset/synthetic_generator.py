"""Generate synthetic training examples for under-represented PII types.

Template-based generation (no LLM calls) using Italian-language templates with
correct character offsets for all entities.

Usage:
    python -m dataset.synthetic_generator
    python -m dataset.synthetic_generator --seed 42 --target-count 5000
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from collections import Counter
from dataclasses import dataclass, asdict, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    text: str
    type: str
    start: int
    end: int


@dataclass
class Example:
    text: str
    entities: list[Entity] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "entities": [asdict(e) for e in self.entities],
        }


# ──────────────────────────────────────────────────────────────────────
# Italian name banks
# ──────────────────────────────────────────────────────────────────────

MALE_NAMES = [
    "Marco", "Giuseppe", "Giovanni", "Antonio", "Francesco", "Mario", "Luigi",
    "Andrea", "Stefano", "Roberto", "Alessandro", "Luca", "Matteo", "Davide",
    "Fabio", "Simone", "Paolo", "Riccardo", "Federico", "Nicola", "Daniele",
    "Massimo", "Claudio", "Enrico", "Alberto", "Lorenzo", "Emanuele", "Filippo",
    "Salvatore", "Vincenzo", "Pietro", "Carlo", "Giorgio", "Gianluca", "Tommaso",
    "Michele", "Angelo", "Enzo", "Sergio", "Gabriele", "Raffaele", "Dario",
    "Cristiano", "Giacomo", "Leonardo", "Edoardo", "Valerio", "Diego", "Samuele",
    "Vittorio",
]

FEMALE_NAMES = [
    "Maria", "Anna", "Giulia", "Francesca", "Sara", "Laura", "Valentina",
    "Chiara", "Alessandra", "Federica", "Silvia", "Elisa", "Martina", "Paola",
    "Monica", "Elena", "Giorgia", "Roberta", "Claudia", "Simona", "Barbara",
    "Daniela", "Cristina", "Sabrina", "Teresa", "Lucia", "Angela", "Ilaria",
    "Michela", "Serena", "Elisabetta", "Veronica", "Marta", "Arianna", "Sofia",
    "Beatrice", "Camilla", "Aurora", "Greta", "Alice", "Irene", "Carlotta",
    "Emma", "Ginevra", "Viola", "Benedetta", "Margherita", "Caterina",
    "Raffaella", "Ornella",
]

SURNAMES = [
    "Rossi", "Russo", "Ferrari", "Esposito", "Bianchi", "Romano", "Colombo",
    "Ricci", "Marino", "Greco", "Bruno", "Gallo", "Conti", "De Luca",
    "Mancini", "Costa", "Giordano", "Rizzo", "Lombardi", "Moretti",
    "Barbieri", "Fontana", "Santoro", "Mariani", "Rinaldi", "Caruso",
    "Ferrara", "Galli", "Martini", "Leone", "Longo", "Gentile", "Martinelli",
    "Vitale", "Lombardo", "Serra", "Coppola", "De Santis", "D'Angelo",
    "Marchetti", "Parisi", "Villa", "Conte", "Ferraro", "Ferri", "Fabbri",
    "Bianco", "Marini", "Grasso", "Valentini",
]

# ──────────────────────────────────────────────────────────────────────
# Italian address components
# ──────────────────────────────────────────────────────────────────────

STREET_TYPES = ["Via", "Corso", "Piazza", "Viale", "Vicolo", "Largo", "Piazzale"]

STREET_NAMES = [
    "Roma", "Garibaldi", "Dante", "Mazzini", "Verdi", "Cavour", "Marconi",
    "Matteotti", "Gramsci", "della Repubblica", "della Libertà", "dei Mille",
    "Europa", "Italia", "Vittorio Emanuele", "XX Settembre", "IV Novembre",
    "Nazionale", "del Corso", "della Stazione", "San Giovanni", "San Marco",
    "dei Fiori", "della Pace", "Leopardi", "Pascoli", "Carducci",
    "Risorgimento", "Trento", "Trieste",
]

CITIES_CAPS = [
    ("Milano", "MI", "20100"), ("Roma", "RM", "00100"), ("Napoli", "NA", "80100"),
    ("Torino", "TO", "10100"), ("Firenze", "FI", "50100"), ("Bologna", "BO", "40100"),
    ("Genova", "GE", "16100"), ("Palermo", "PA", "90100"), ("Bari", "BA", "70100"),
    ("Catania", "CT", "95100"), ("Venezia", "VE", "30100"), ("Verona", "VR", "37100"),
    ("Padova", "PD", "35100"), ("Trieste", "TS", "34100"), ("Brescia", "BS", "25100"),
    ("Bergamo", "BG", "24100"), ("Modena", "MO", "41100"), ("Parma", "PR", "43100"),
    ("Perugia", "PG", "06100"), ("Reggio Emilia", "RE", "42100"),
    ("Cagliari", "CA", "09100"), ("Livorno", "LI", "57100"), ("Ravenna", "RA", "48100"),
    ("Rimini", "RN", "47900"), ("Salerno", "SA", "84100"), ("Pisa", "PI", "56100"),
    ("Lecce", "LE", "73100"), ("Ancona", "AN", "60100"), ("Pescara", "PE", "65100"),
    ("Como", "CO", "22100"),
]

# ──────────────────────────────────────────────────────────────────────
# Medical terms
# ──────────────────────────────────────────────────────────────────────

CONDITIONS = [
    "diabete di tipo 2", "ipertensione arteriosa", "asma bronchiale",
    "insufficienza renale cronica", "artrite reumatoide", "depressione maggiore",
    "fibrillazione atriale", "scompenso cardiaco", "morbo di Parkinson",
    "sclerosi multipla", "epilessia", "cirrosi epatica", "celiachia",
    "ipotiroidismo", "anemia falciforme", "lupus eritematoso sistemico",
    "fibromialgia", "sindrome metabolica", "broncopneumopatia cronica ostruttiva",
    "epatite C", "insufficienza cardiaca congestizia", "schizofrenia",
    "disturbo bipolare", "malattia di Crohn", "colite ulcerosa",
]

HOSPITALS = [
    "ospedale San Raffaele", "policlinico Gemelli", "ospedale Niguarda",
    "ospedale Molinette", "policlinico di Milano", "ospedale Bambino Gesù",
    "ospedale Sant'Orsola", "ospedale Careggi", "ospedale Cotugno",
    "policlinico Umberto I", "ospedale San Martino", "ospedale Cisanello",
    "ospedale Le Molinette", "ospedale Maggiore", "policlinico San Matteo",
]

DRUGS = [
    "metformina", "enalapril", "salbutamolo", "omeprazolo", "atorvastatina",
    "amlodipina", "ramipril", "furosemide", "metoprololo", "losartan",
    "simvastatina", "levotiroxina", "warfarin", "insulina glargine",
    "pantoprazolo", "bisoprololo", "valsartan", "clopidogrel",
]

# ──────────────────────────────────────────────────────────────────────
# Legal terms
# ──────────────────────────────────────────────────────────────────────

TRIBUNALI = [
    "Roma", "Milano", "Napoli", "Torino", "Palermo", "Firenze", "Bologna",
    "Genova", "Bari", "Catania", "Venezia", "Brescia", "Padova", "Verona",
]

# ──────────────────────────────────────────────────────────────────────
# Relationships
# ──────────────────────────────────────────────────────────────────────

RELATIONS = [
    "mio fratello", "mia sorella", "mio padre", "mia madre", "mio figlio",
    "mia figlia", "mio marito", "mia moglie", "il mio collega", "la mia collega",
    "il mio capo", "il mio vicino di casa", "la mia ex", "il mio ex",
    "il mio socio", "la mia socia", "mio zio", "mia zia", "mio cugino",
    "mia cugina", "il mio coinquilino", "il mio compagno", "la mia compagna",
    "mio nonno", "mia nonna", "il mio suocero", "mia suocera",
]

# Map each relation phrase to the grammatical gender of the referred person,
# so that the accompanying first name always matches.
# "m" → pick from MALE_NAMES, "f" → pick from FEMALE_NAMES
RELATION_GENDER: dict[str, str] = {
    "mio fratello": "m",
    "mia sorella": "f",
    "mio padre": "m",
    "mia madre": "f",
    "mio figlio": "m",
    "mia figlia": "f",
    "mio marito": "m",
    "mia moglie": "f",
    "il mio collega": "m",
    "la mia collega": "f",
    "il mio capo": "m",
    "il mio vicino di casa": "m",
    "la mia ex": "f",
    "il mio ex": "m",
    "il mio socio": "m",
    "la mia socia": "f",
    "mio zio": "m",
    "mia zia": "f",
    "mio cugino": "m",
    "mia cugina": "f",
    "il mio coinquilino": "m",
    "il mio compagno": "m",
    "la mia compagna": "f",
    "mio nonno": "m",
    "mia nonna": "f",
    "il mio suocero": "m",
    "mia suocera": "f",
}

RELATION_TEMPLATES = [
    "{rel} {name} mi ha detto che",
    "Ho sentito {rel} {name} ieri sera",
    "{rel} {name} lavora come {job}",
    "Sono stato a cena da {rel} {name}",
    "Devo chiamare {rel} {name} per la questione",
    "{rel} {name} ha avuto un problema",
    "Secondo {rel} {name} dovremmo aspettare",
]

# ──────────────────────────────────────────────────────────────────────
# Professions (identifying)
#
# Each entry is a tuple (sentence_prefix, profession_core, sentence_suffix).
# The entity span covers ONLY the profession_core part; the prefix/suffix
# are part of the containing sentence but not the entity itself.
# ``{street}`` placeholders are substituted from STREET_NAMES at generation time.
# ──────────────────────────────────────────────────────────────────────

PROFESSIONS: list[tuple[str, str, str]] = [
    ("il ",      "notaio",              " del paese"),
    ("il ",      "farmacista",          " di via {street}"),
    ("l'unico ", "dentista",            " del quartiere"),
    ("il ",      "medico di base",      " del distretto"),
    ("il ",      "parroco",             " di San Giovanni"),
    ("la ",      "maestra",             " della terza B"),
    ("il ",      "sindaco",             " del comune"),
    ("l'",       "avvocato penalista",  ""),
    ("il ",      "commercialista",      " dello studio"),
    ("il ",      "geometra",            " del cantiere"),
    ("il ",      "veterinario",         " di zona"),
    ("il ",      "barbiere",            " di piazza {street}"),
    ("l'",       "edicolante",          " di corso {street}"),
    ("il ",      "portinaio",           " del palazzo"),
    ("la ",      "pediatra",            " dei miei figli"),
    ("il ",      "chirurgo",            " del reparto"),
]

# ──────────────────────────────────────────────────────────────────────
# Italian discursive date components
# ──────────────────────────────────────────────────────────────────────

MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]

GIORNI_PAROLA = {
    1: "primo", 2: "due", 3: "tre", 4: "quattro", 5: "cinque",
    6: "sei", 7: "sette", 8: "otto", 9: "nove", 10: "dieci",
    11: "undici", 12: "dodici", 13: "tredici", 14: "quattordici",
    15: "quindici", 16: "sedici", 17: "diciassette", 18: "diciotto",
    19: "diciannove", 20: "venti", 21: "ventuno", 22: "ventidue",
    23: "ventitre", 24: "ventiquattro", 25: "venticinque",
    26: "ventisei", 27: "ventisette", 28: "ventotto", 29: "ventinove",
    30: "trenta", 31: "trentuno",
}

NUMERI_32_49 = {
    32: "trentadue", 33: "trentatré", 34: "trentaquattro", 35: "trentacinque",
    36: "trentasei", 37: "trentasette", 38: "trentotto", 39: "trentanove",
    40: "quaranta", 41: "quarantuno", 42: "quarantadue", 43: "quarantatré",
    44: "quarantaquattro", 45: "quarantacinque", 46: "quarantasei",
    47: "quarantasette", 48: "quarantotto", 49: "quarantanove",
}

DECADI = {
    50: "cinquanta", 51: "cinquantuno", 52: "cinquantadue",
    53: "cinquantatre", 54: "cinquantaquattro", 55: "cinquantacinque",
    56: "cinquantasei", 57: "cinquantasette", 58: "cinquantotto",
    59: "cinquantanove",
    60: "sessanta", 61: "sessantuno", 62: "sessantadue",
    63: "sessantatre", 64: "sessantaquattro", 65: "sessantacinque",
    66: "sessantasei", 67: "sessantasette", 68: "sessantotto",
    69: "sessantanove",
    70: "settanta", 71: "settantuno", 72: "settantadue",
    73: "settantatre", 74: "settantaquattro", 75: "settantacinque",
    76: "settantasei", 77: "settantasette", 78: "settantotto",
    79: "settantanove",
    80: "ottanta", 81: "ottantuno", 82: "ottantadue",
    83: "ottantatre", 84: "ottantaquattro", 85: "ottantacinque",
    86: "ottantasei", 87: "ottantasette", 88: "ottantotto",
    89: "ottantanove",
    90: "novanta", 91: "novantuno", 92: "novantadue",
    93: "novantatre", 94: "novantaquattro", 95: "novantacinque",
    96: "novantasei", 97: "novantasette", 98: "novantotto",
    99: "novantanove",
}

ANNI_PAROLA = {
    **{y: f"millenovecento{DECADI[y - 1900]}" for y in range(1950, 2000)},
    2000: "duemila",
    **{y: f"duemila{DECADI.get(y - 2000, str(y - 2000))}" for y in range(2001, 2010) if y - 2000 in DECADI},
}
# Fill in years 2001-2009 manually
ANNI_PAROLA[2001] = "duemilauno"
ANNI_PAROLA[2002] = "duemiladue"
ANNI_PAROLA[2003] = "duemilatre"
ANNI_PAROLA[2004] = "duemilaquattro"
ANNI_PAROLA[2005] = "duemilacinque"
ANNI_PAROLA[2006] = "duemilasei"
ANNI_PAROLA[2007] = "duemilasette"
ANNI_PAROLA[2008] = "duemilaotto"
ANNI_PAROLA[2009] = "duemilanove"


JOBS = [
    "ingegnere", "avvocato", "medico", "commercialista", "architetto",
    "insegnante", "infermiere", "geometra", "elettricista", "idraulico",
    "programmatore", "giornalista", "cuoco", "farmacista", "dentista",
]


def _random_name(rng: random.Random, gender: str | None = None) -> str:
    """Return a random Italian full name.

    Args:
        rng:    seeded random instance.
        gender: ``"m"`` forces a male first name, ``"f"`` forces a female
                first name.  ``None`` (default) picks either at random.
    """
    if gender == "m":
        first = rng.choice(MALE_NAMES)
    elif gender == "f":
        first = rng.choice(FEMALE_NAMES)
    else:
        first = rng.choice(MALE_NAMES + FEMALE_NAMES)
    last = rng.choice(SURNAMES)
    return f"{first} {last}"


def _random_address(rng: random.Random) -> str:
    street_type = rng.choice(STREET_TYPES)
    street_name = rng.choice(STREET_NAMES)
    number = rng.randint(1, 200)
    city, prov, cap = rng.choice(CITIES_CAPS)
    return f"{street_type} {street_name} {number}, {cap} {city} ({prov})"


def _make_example(text: str, entities: list[Entity]) -> Example:
    """Create an Example and assert offset correctness."""
    for e in entities:
        assert text[e.start:e.end] == e.text, (
            f"Offset mismatch: text[{e.start}:{e.end}]='{text[e.start:e.end]}' "
            f"!= entity.text='{e.text}'"
        )
    return Example(text=text, entities=entities)


# ──────────────────────────────────────────────────────────────────────
# Generator functions per type
# ──────────────────────────────────────────────────────────────────────


def _generate_pe(rng: random.Random, count: int) -> list[Example]:
    """Generate persona (pe) examples."""
    templates = [
        ("Senti {name} dimmi quando arrivi", "Senti ", " dimmi quando arrivi"),
        ("Ho parlato con {name} ieri sera al telefono", "Ho parlato con ", " ieri sera al telefono"),
        ("Il signor {name} ha chiamato stamattina", "Il signor ", " ha chiamato stamattina"),
        ("Buongiorno, sono {name} e vorrei un appuntamento", "Buongiorno, sono ", " e vorrei un appuntamento"),
        ("La pratica è intestata a {name} dal 2020", "La pratica è intestata a ", " dal 2020"),
        ("Chiedi a {name} se può venire domani", "Chiedi a ", " se può venire domani"),
        ("Mi ha risposto {name} con un messaggio", "Mi ha risposto ", " con un messaggio"),
        ("Il dottor {name} riceve il martedì", "Il dottor ", " riceve il martedì"),
        ("Devo sentire {name} per la consegna", "Devo sentire ", " per la consegna"),
        ("Saluta {name} da parte mia", "Saluta ", " da parte mia"),
        ("{name} mi deve ancora dei soldi", "", " mi deve ancora dei soldi"),
        ("La signora {name} è passata in ufficio", "La signora ", " è passata in ufficio"),
        ("Ho un appuntamento con {name} alle tre", "Ho un appuntamento con ", " alle tre"),
        ("Vorrei parlare con {name} per favore", "Vorrei parlare con ", " per favore"),
        ("{name} ha confermato la prenotazione", "", " ha confermato la prenotazione"),
    ]

    examples: list[Example] = []
    for _ in range(count):
        name = _random_name(rng)
        prefix, suffix = rng.choice(templates)[1:]
        text = f"{prefix}{name}{suffix}"
        start = len(prefix)
        end = start + len(name)
        examples.append(_make_example(text, [Entity(text=name, type="pe", start=start, end=end)]))

    return examples


def _generate_ind(rng: random.Random, count: int) -> list[Example]:
    """Generate indirizzo (ind) examples."""
    templates = [
        ("Abito in {addr} da cinque anni", "Abito in ", " da cinque anni"),
        ("La sede è in {addr}", "La sede è in ", ""),
        ("Spedisci tutto a {addr}", "Spedisci tutto a ", ""),
        ("Il cantiere si trova in {addr}", "Il cantiere si trova in ", ""),
        ("L'indirizzo di consegna è {addr}", "L'indirizzo di consegna è ", ""),
        ("Mi trovi in {addr} dopo le cinque", "Mi trovi in ", " dopo le cinque"),
        ("Ho traslocato in {addr} il mese scorso", "Ho traslocato in ", " il mese scorso"),
        ("Il negozio è situato in {addr}", "Il negozio è situato in ", ""),
        ("Mandami il pacco a {addr} per cortesia", "Mandami il pacco a ", " per cortesia"),
        ("Il laboratorio è in {addr}", "Il laboratorio è in ", ""),
    ]

    examples: list[Example] = []
    for _ in range(count):
        addr = _random_address(rng)
        prefix, suffix = rng.choice(templates)[1:]
        text = f"{prefix}{addr}{suffix}"
        start = len(prefix)
        end = start + len(addr)
        examples.append(_make_example(text, [Entity(text=addr, type="ind", start=start, end=end)]))

    return examples


def _generate_dt(rng: random.Random, count: int) -> list[Example]:
    """Generate data nascita discorsiva (dt) examples.

    Only fully-discursive date expressions are generated here.  Structured /
    semi-structured formats that the regex engine already handles are excluded:

      EXCLUDED (regex territory):
        - "3 marzo" / "3/03" — numeric day + month name or slash-date
        - "1985" / "classe 1985" — bare 4-digit year
        - ISO dates (YYYY-MM-DD) and DD/MM/YYYY patterns

      INCLUDED (discursive only):
        variant 0 – "quindici marzo del millenovecentottantacinque"  (all words)
        variant 1 – "sessantadue"  (short year word)
        variant 2 – "di anni ne ha settantadue"  (age in words)
        variant 3 – "ventitre aprile millenovecentottantacinque"  (day+month+year all words, no "del")
    """
    examples: list[Example] = []

    for _ in range(count):
        variant = rng.randint(0, 3)

        if variant == 0:
            # "nato il quindici marzo del millenovecentottantacinque"
            day = rng.randint(1, 28)
            month = rng.randint(1, 12)
            year = rng.randint(1950, 2005)
            day_word = GIORNI_PAROLA[day]
            month_word = MESI[month - 1]
            year_word = ANNI_PAROLA.get(year, str(year))
            date_str = f"{day_word} {month_word} del {year_word}"
            prefix = rng.choice(["Sono nato il ", "È nato il ", "Nata il "])
            text = f"{prefix}{date_str}"
            start = len(prefix)

        elif variant == 1:
            # "è del sessantadue" — short year in words only
            year_short = rng.randint(50, 99)
            year_word = DECADI.get(year_short, str(year_short))
            date_str = year_word
            prefix = rng.choice(["È del ", "Sono del ", "Lei è del "])
            text = f"{prefix}{date_str}"
            start = len(prefix)

        elif variant == 2:
            # "di anni ne ha settantadue" — age expressed entirely in words
            age = rng.randint(18, 90)
            age_word = DECADI.get(age) or GIORNI_PAROLA.get(age, str(age))
            date_str = age_word
            prefix = rng.choice(["Di anni ne ha ", "Ha compiuto ", "Avrà "])
            suffix = rng.choice([" anni", " anni il mese scorso", ""])
            text = f"{prefix}{date_str}{suffix}"
            start = len(prefix)

        else:
            # "ventitre aprile millenovecentottantacinque" — day+month+year all in words
            day = rng.randint(1, 28)
            month = rng.randint(1, 12)
            year = rng.randint(1950, 2005)
            day_word = GIORNI_PAROLA[day]
            month_word = MESI[month - 1]
            year_word = ANNI_PAROLA.get(year, str(year))
            date_str = f"{day_word} {month_word} {year_word}"
            prefix = rng.choice([
                "Nato il ", "La data di nascita è il ",
                "Risulta nato il ", "Data di nascita: ",
            ])
            text = f"{prefix}{date_str}"
            start = len(prefix)

        end = start + len(date_str)
        examples.append(_make_example(text, [Entity(text=date_str, type="dt", start=start, end=end)]))

    return examples


def _generate_med(rng: random.Random, count: int) -> list[Example]:
    """Generate medico (med) examples."""
    examples: list[Example] = []

    for _ in range(count):
        variant = rng.randint(0, 4)

        if variant == 0:
            # Condition
            condition = rng.choice(CONDITIONS)
            prefix = rng.choice([
                "Mi hanno diagnosticato ",
                "Soffro di ",
                "È in cura per ",
                "Ha una storia di ",
                "Il paziente presenta ",
            ])
            suffix = rng.choice([
                " da tre anni",
                " dall'anno scorso",
                " e prende farmaci",
                "",
                " cronica",
            ])
            text = f"{prefix}{condition}{suffix}"
            start = len(prefix)
            end = start + len(condition)
            examples.append(_make_example(text, [Entity(text=condition, type="med", start=start, end=end)]))

        elif variant == 1:
            # Hospital — tagged as org (facility name, not medical condition)
            hospital = rng.choice(HOSPITALS)
            prefix = rng.choice([
                "È ricoverato al ",
                "L'intervento si fa al ",
                "Sono stato al ",
                "La visita è al ",
            ])
            suffix = rng.choice([" la settimana prossima", " domani", "", " per un controllo"])
            text = f"{prefix}{hospital}{suffix}"
            start = len(prefix)
            end = start + len(hospital)
            examples.append(_make_example(text, [Entity(text=hospital, type="org", start=start, end=end)]))

        elif variant == 2:
            # Drug + condition
            drug = rng.choice(DRUGS)
            condition = rng.choice(CONDITIONS)
            text = f"Prende {drug} per {condition}"
            drug_start = len("Prende ")
            drug_end = drug_start + len(drug)
            cond_start = drug_end + len(" per ")
            cond_end = cond_start + len(condition)
            examples.append(_make_example(text, [
                Entity(text=drug, type="med", start=drug_start, end=drug_end),
                Entity(text=condition, type="med", start=cond_start, end=cond_end),
            ]))

        elif variant == 3:
            # Doctor reference
            name = _random_name(rng)
            prefix = rng.choice(["Il dottor ", "La dottoressa ", "Il professor "])
            suffix = rng.choice([
                " gli ha prescritto riposo",
                " ha detto di tornare fra un mese",
                " è il suo specialista",
                " lo segue da anni",
            ])
            text = f"{prefix}{name}{suffix}"
            start = len(prefix)
            end = start + len(name)
            examples.append(_make_example(text, [Entity(text=name, type="pe", start=start, end=end)]))

        else:
            # Drug alone
            drug = rng.choice(DRUGS)
            prefix = rng.choice([
                "Prende ",
                "Gli hanno prescritto ",
                "Assume quotidianamente ",
                "È in terapia con ",
            ])
            suffix = rng.choice([
                " due volte al giorno",
                " da sei mesi",
                " 500mg al giorno",
                "",
            ])
            text = f"{prefix}{drug}{suffix}"
            start = len(prefix)
            end = start + len(drug)
            examples.append(_make_example(text, [Entity(text=drug, type="med", start=start, end=end)]))

    return examples


def _generate_leg(rng: random.Random, count: int) -> list[Example]:
    """Generate legale (leg) examples.

    Variants:
      0 – full case reference (causa n. NNN/YYYY presso il tribunale di …)  → leg
      1 – criminal/civil proceeding number                                   → leg
      2 – court decision reference (sentenza/decreto/ordinanza del …)        → leg
      3 – law firm name (Studio Legale …)                                     → org
          Law firms are organisations, not legal-proceeding references.

    Variant 3 is kept as a generator because the sentence context is legal, but
    the entity is correctly tagged ``org`` so the model learns to distinguish
    between a legal-proceeding entity and a law-firm organisation.
    """
    examples: list[Example] = []

    for _ in range(count):
        variant = rng.randint(0, 3)

        if variant == 0:
            # Full case reference: "causa n. 6999/2025 presso il tribunale di Bari"
            num = rng.randint(100, 9999)
            year = rng.randint(2018, 2026)
            city = rng.choice(TRIBUNALI)
            case_ref = f"n. {num}/{year}"
            leg_text = f"causa {case_ref} presso il tribunale di {city}"
            prefix = rng.choice([
                "La ", "Si tratta della ", "È pendente la ", "Riguardo alla ",
            ])
            text = f"{prefix}{leg_text}"
            start = len(prefix)
            end = start + len(leg_text)
            examples.append(_make_example(text, [Entity(text=leg_text, type="leg", start=start, end=end)]))

        elif variant == 1:
            # Criminal / civil proceeding number
            num = rng.randint(100, 9999)
            year = rng.randint(2018, 2026)
            city = rng.choice(TRIBUNALI)
            proc_type = rng.choice([
                "procedimento penale", "procedimento civile", "ricorso",
            ])
            leg_text = f"{proc_type} n. {num}/{year} presso il tribunale di {city}"
            prefix = rng.choice([
                "È in corso il ", "Ho ricevuto notifica del ",
                "Riguardo al ", "Si riferisce al ",
            ])
            text = f"{prefix}{leg_text}"
            start = len(prefix)
            end = start + len(leg_text)
            examples.append(_make_example(text, [Entity(text=leg_text, type="leg", start=start, end=end)]))

        elif variant == 2:
            # Court decision reference
            city = rng.choice(TRIBUNALI)
            decision_type = rng.choice(["sentenza", "decreto", "ordinanza"])
            year = rng.randint(2020, 2026)
            leg_text = f"{decision_type} del tribunale di {city} del {year}"
            prefix = rng.choice([
                "In base alla ", "Come previsto dalla ",
                "A seguito della ", "Secondo la ",
            ])
            text = f"{prefix}{leg_text}"
            start = len(prefix)
            end = start + len(leg_text)
            examples.append(_make_example(text, [Entity(text=leg_text, type="leg", start=start, end=end)]))

        else:
            # Law firm → org (not leg: a firm name is an organisation reference)
            surname1 = rng.choice(SURNAMES)
            surname2 = rng.choice(SURNAMES)
            while surname2 == surname1:
                surname2 = rng.choice(SURNAMES)
            firm = f"Studio Legale {surname1} & {surname2}"
            prefix = rng.choice([
                "Mi sono rivolto allo ",
                "Ho contattato lo ",
                "Ci rappresenta lo ",
                "Il mio avvocato lavora nello ",
            ])
            suffix = rng.choice([" per la vertenza", " di Milano", "", " che ci segue"])
            text = f"{prefix}{firm}{suffix}"
            start = len(prefix)
            end = start + len(firm)
            # Correctly tagged as org, not leg
            examples.append(_make_example(text, [Entity(text=firm, type="org", start=start, end=end)]))

    return examples


def _generate_rel(rng: random.Random, count: int) -> list[Example]:
    """Generate relazione (rel) examples.

    The first name in the entity is gender-matched to the relationship word
    (e.g. ``mia figlia`` always gets a female name, ``mio zio`` a male name).
    """
    examples: list[Example] = []

    for _ in range(count):
        rel = rng.choice(RELATIONS)
        gender = RELATION_GENDER.get(rel)          # "m", "f", or None
        name = _random_name(rng, gender=gender)    # gender-correct first name
        job = rng.choice(JOBS)

        tpl = rng.choice(RELATION_TEMPLATES)
        sentence = tpl.format(rel=rel, name=name, job=job)

        # Find the relation + name span
        rel_name = f"{rel} {name}"
        idx = sentence.find(rel_name)
        if idx == -1:
            continue

        entities = [
            Entity(text=rel_name, type="rel", start=idx, end=idx + len(rel_name)),
        ]
        examples.append(_make_example(sentence, entities))

    return examples


def _generate_fin(rng: random.Random, count: int) -> list[Example]:
    """Generate finanziario (fin) examples.

    All entities are *contextual* financial references that require semantic
    understanding to detect — the regex engine handles bare numeric patterns
    (e.g. ``50€``, ``1.200,00 EUR``) so those are excluded here.

    The entity span covers the full contextual phrase:
      "stipendio di 2.400 euro", "fattura da 15.000 euro", "debito di 50.000 euro con Unicredit"

    Variants:
      0 – income/salary reference     ("stipendio di N euro")
      1 – invoice / bill reference    ("fattura da N euro")
      2 – debt reference              ("debito di N euro con <bank>")
      3 – named-person debt (pe + fin)
    """
    BANKS = [
        "Unicredit", "Intesa Sanpaolo", "BNL", "Banco BPM",
        "Mediobanca", "Monte dei Paschi", "Credem", "Banca Sella",
    ]

    examples: list[Example] = []

    for _ in range(count):
        variant = rng.randint(0, 3)
        # Amounts intentionally in a range that looks human / non-trivial
        amount_val = rng.choice([
            rng.randint(800, 3000),      # typical salary / invoice range
            rng.randint(3000, 20000),    # larger invoice / loan instalment
            rng.randint(20000, 150000),  # mortgage / significant debt
        ])
        # Format with Italian thousands separator (dot) and no decimal fraction
        amount_num = f"{amount_val:,}".replace(",", ".")

        if variant == 0:
            # Income/salary: entity = "stipendio di N.NNN euro [al mese|annuo]"
            label = rng.choice(["stipendio di", "reddito mensile di", "RAL di"])
            period = rng.choice([" euro al mese", " euro annui", " euro netti"])
            amount = f"{label} {amount_num}{period}"
            prefix = rng.choice([
                "Prende un ", "Ha dichiarato un ", "Il suo ", "Con un ",
            ])
            text = f"{prefix}{amount}"
            start = len(prefix)
            end = start + len(amount)

        elif variant == 1:
            # Invoice / payment: entity = "fattura da N.NNN euro"
            label = rng.choice(["fattura da", "parcella da", "preventivo da"])
            amount = f"{label} {amount_num} euro"
            prefix = rng.choice([
                "Ho ricevuto una ", "Mi ha mandato una ", "Ha emesso una ",
                "È arrivata una ",
            ])
            suffix = rng.choice([
                " non ancora pagata",
                " da saldare entro trenta giorni",
                " per i lavori eseguiti",
                "",
            ])
            text = f"{prefix}{amount}{suffix}"
            start = len(prefix)
            end = start + len(amount)

        elif variant == 2:
            # Debt with bank: entity = "debito di N.NNN euro con <Bank>"
            bank = rng.choice(BANKS)
            label = rng.choice(["debito di", "prestito di", "mutuo da"])
            amount = f"{label} {amount_num} euro con {bank}"
            prefix = rng.choice([
                "Ha un ", "C'è un ", "Risulta un ", "Sta pagando un ",
            ])
            text = f"{prefix}{amount}"
            start = len(prefix)
            end = start + len(amount)

        else:
            # Named-person debt: <person> mi deve <amount>  (pe + fin entities)
            amount = f"{amount_num} euro"
            name = _random_name(rng)
            label = rng.choice(["mi deve", "ci deve", "gli deve"])
            text = f"{name} {label} {amount} da {rng.choice(['giugno', 'mesi', 'quest anno', 'sempre'])}"
            name_start = 0
            name_end = len(name)
            amount_start = name_end + len(f" {label} ")
            amount_end = amount_start + len(amount)
            examples.append(_make_example(text, [
                Entity(text=name, type="pe", start=name_start, end=name_end),
                Entity(text=amount, type="fin", start=amount_start, end=amount_end),
            ]))
            continue

        examples.append(_make_example(text, [Entity(text=amount, type="fin", start=start, end=end)]))

    return examples


def _generate_pro(rng: random.Random, count: int) -> list[Example]:
    """Generate professione (pro) examples.

    The entity span covers only the profession core (e.g. ``"medico di base"``).
    Surrounding context words such as ``"il"`` / ``"del distretto"`` appear in the
    sentence but are NOT part of the entity.
    """
    examples: list[Example] = []

    sentence_prefixes = [
        "Conosco ", "Ho parlato con ", "Devi sentire ", "Chiedi a ",
        "Me lo ha detto ", "Secondo ",
    ]
    sentence_suffixes = [
        " e mi ha consigliato di aspettare",
        " che è molto bravo",
        "",
        " per un parere",
        " la settimana scorsa",
    ]

    for _ in range(count):
        street = rng.choice(STREET_NAMES)
        ctx_prefix, prof_core, ctx_suffix = rng.choice(PROFESSIONS)

        # Substitute {street} placeholder where present
        ctx_prefix = ctx_prefix.replace("{street}", street)
        prof_core = prof_core.replace("{street}", street)
        ctx_suffix = ctx_suffix.replace("{street}", street)

        sentence_prefix = rng.choice(sentence_prefixes)
        sentence_suffix = rng.choice(sentence_suffixes)

        # Full text: <sentence_prefix><ctx_prefix><prof_core><ctx_suffix><sentence_suffix>
        text = f"{sentence_prefix}{ctx_prefix}{prof_core}{ctx_suffix}{sentence_suffix}"

        # Entity start/end covers prof_core only
        start = len(sentence_prefix) + len(ctx_prefix)
        end = start + len(prof_core)

        examples.append(_make_example(text, [Entity(text=prof_core, type="pro", start=start, end=end)]))

    return examples


# ──────────────────────────────────────────────────────────────────────
# Main generator
# ──────────────────────────────────────────────────────────────────────


def generate_synthetic(
    output_dir: Path,
    seed: int = 42,
    target_count: int = 5000,
) -> None:
    """Generate synthetic examples and save to JSONL."""
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Distribute target_count across types proportionally to the spec
    # pe:500, ind:800, dt:500, med:600, leg:500, rel:500, fin:400, pro:400
    total_spec = 500 + 800 + 500 + 600 + 500 + 500 + 400 + 400  # 4200
    scale = target_count / total_spec

    type_counts = {
        "pe": max(1, int(500 * scale)),
        "ind": max(1, int(800 * scale)),
        "dt": max(1, int(500 * scale)),
        "med": max(1, int(600 * scale)),
        "leg": max(1, int(500 * scale)),
        "rel": max(1, int(500 * scale)),
        "fin": max(1, int(400 * scale)),
        "pro": max(1, int(400 * scale)),
    }

    generators = {
        "pe": _generate_pe,
        "ind": _generate_ind,
        "dt": _generate_dt,
        "med": _generate_med,
        "leg": _generate_leg,
        "rel": _generate_rel,
        "fin": _generate_fin,
        "pro": _generate_pro,
    }

    all_examples: list[Example] = []
    entity_counter: Counter = Counter()

    for type_code, gen_count in type_counts.items():
        logger.info("Generating %d examples for type '%s'", gen_count, type_code)
        examples = generators[type_code](rng, gen_count)
        all_examples.extend(examples)
        for ex in examples:
            for ent in ex.entities:
                entity_counter[ent.type] += 1

    # Shuffle for variety
    rng.shuffle(all_examples)

    # Save
    output_path = output_dir / "synthetic.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in all_examples:
            f.write(json.dumps(ex.to_dict(), ensure_ascii=False) + "\n")

    # Print stats
    print(f"\n{'=' * 60}")
    print(f"Synthetic Generation Complete")
    print(f"  Total examples:  {len(all_examples):,}")
    print(f"  Target count:    {target_count:,}")
    print(f"  Entity counts:")
    for etype, count in sorted(entity_counter.items()):
        print(f"    {etype:6s}: {count:,}")
    print(f"  Output: {output_path}")
    print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic PII training examples for Privacy Shield."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/synthetic"),
        help="Output directory for synthetic data (default: data/synthetic)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=5000,
        help="Target number of synthetic examples (default: 5000)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    generate_synthetic(args.output_dir, args.seed, args.target_count)


if __name__ == "__main__":
    main()
