"""Entity type mappings for Privacy Shield PII detection.

Maps source dataset entity types to Privacy Shield compact codes.
These codes are used in training data, model output, and span_fusion.py integration.
"""

# Privacy Shield PII type codes (SLM-only, complementary to regex engine)
PS_TYPES = {
    "pe": "persona",
    "org": "organizzazione",
    "loc": "località",
    "ind": "indirizzo",
    "med": "medico",
    "leg": "legale",
    "rel": "relazione",
    "fin": "finanziario",
    "pro": "professione",
    "dt": "data nascita discorsiva",
}

# Types handled by regex engine (EXCLUDED from SLM training data)
REGEX_TYPES = {"cf", "ib", "em", "tel"}

# MultiNERD type mapping → PS codes
MULTINERD_MAP = {
    "PER": "pe",
    "ORG": "org",
    "LOC": "loc",
    "DIS": "med",
    "INST": "org",
    # Skipped types (not PII-relevant):
    # ANIM, CEL, EVE, FOOD, MEDIA, MYTH, PLANT, TIME, VEHI
}

# WikiNEuRal type mapping → PS codes
WIKINEURAL_MAP = {
    "PER": "pe",
    "ORG": "org",
    "LOC": "loc",
    # MISC → skip (too heterogeneous)
}

# ai4privacy type mapping → PS codes
# ai4privacy uses fine-grained types; map the relevant ones
AI4PRIVACY_MAP = {
    # Person
    "FIRSTNAME": "pe",
    "LASTNAME": "pe",
    "GIVENNAME": "pe",
    "SURNAME": "pe",
    "FULLNAME": "pe",
    "USERNAME": "pe",
    "PREFIX": None,  # Mr/Mrs - not PII
    "TITLE": None,
    # Organization
    "COMPANYNAME": "org",
    "ORGANIZATIONNAME": "org",
    # Location
    "CITY": "loc",
    "STATE": "loc",
    "COUNTRY": "loc",
    "COUNTY": "loc",
    "STREET": "ind",
    "STREETADDRESS": "ind",
    "BUILDINGNUMBER": "ind",
    "ZIPCODE": "ind",
    "SECONDARYADDRESS": "ind",
    "NEARBYGPSCOORDINATE": "loc",
    # Medical
    "DISEASE": "med",
    "BLOODTYPE": "med",
    "HEIGHT": "med",
    "WEIGHT": "med",
    "EYECOLOR": None,  # not medical PII in our scope
    # Financial
    "AMOUNT": "fin",
    "CURRENCY": None,  # not PII alone
    "CREDITCARDNUMBER": None,  # regex handles
    "IBAN": None,  # regex handles
    "BIC": None,
    "ACCOUNTNUMBER": "fin",
    "BITCOINADDRESS": "fin",
    "ETHEREUMADDRESS": "fin",
    "LITECOINADDRESS": "fin",
    # Professional
    "JOBTITLE": "pro",
    "JOBAREA": "pro",
    "JOBTYPE": "pro",
    # Date
    "DOB": "dt",
    "DATEOFBIRTH": "dt",
    "DATE": None,  # generic dates not PII
    "TIME": None,
    # Regex-handled (EXCLUDE from SLM data)
    "EMAIL": None,
    "PHONENUMBER": None,
    "PHONE_NUMBER": None,
    "IP": None,
    "IMEI": None,
    "MAC": None,
    "URL": None,
    "SSN": None,
    "TAXID": None,
    "VEHICLEIDENTIFICATIONNUMBER": None,
    "VEHICLEVRM": None,
    "DRIVINGLICENSE": None,
    "PASSPORT": None,
    # Identity (skip - regex or not PII)
    "GENDER": None,
    "SEX": None,
    "MIDDLENAME": "pe",
    "AGE": None,
    "USERAGENT": None,
    "PASSWORD": None,
    "PIN": None,
}

# HUMADEX Italian NER mapping
HUMADEX_MAP = {
    "DISEASE": "med",
    "SYMPTOM": "med",
    "DRUG": "med",
    "TREATMENT": "med",
    "BODY_PART": None,  # not PII
    "TEST": None,
}


# ---------------------------------------------------------------------------
# NER (Token Classification) label system — BIO tagging
# ---------------------------------------------------------------------------

NER_LABELS = [
    "O",
    "B-pe", "I-pe", "B-org", "I-org", "B-loc", "I-loc",
    "B-ind", "I-ind", "B-med", "I-med", "B-leg", "I-leg",
    "B-rel", "I-rel", "B-fin", "I-fin", "B-pro", "I-pro",
    "B-dt", "I-dt",
]
LABEL2ID = {label: idx for idx, label in enumerate(NER_LABELS)}
ID2LABEL = {idx: label for idx, label in enumerate(NER_LABELS)}
NUM_LABELS = len(NER_LABELS)  # 21


def map_entity_type(source_type: str, source_dataset: str) -> str | None:
    """Map a source dataset entity type to a PS type code.

    Returns None if the type should be excluded (handled by regex or not PII).
    """
    mapping = {
        "multinerd": MULTINERD_MAP,
        "wikineural": WIKINEURAL_MAP,
        "ai4privacy_500k": AI4PRIVACY_MAP,
        "ai4privacy_400k": AI4PRIVACY_MAP,
        "ai4privacy_200k": AI4PRIVACY_MAP,
        "humadex": HUMADEX_MAP,
    }
    type_map = mapping.get(source_dataset, {})
    return type_map.get(source_type)


# System prompt used in training and production (single source of truth)
SYSTEM_PROMPT = (
    "Sei il motore PII del sistema Privacy Shield. "
    "Dato un testo, identifica le informazioni personali NON catturabili da regex "
    "(no email, telefono, IBAN, codice fiscale, P.IVA, date in formato DD/MM/YYYY).\n"
    "Tipi: pe (persona), org (organizzazione), loc (località), ind (indirizzo), "
    "med (medico), leg (legale), rel (relazione), fin (finanziario), "
    "pro (professione), dt (data nascita discorsiva).\n"
    "Restituisci SOLO un array JSON. Se nessuna PII: []."
)
