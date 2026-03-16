"""Generate hard-negative examples (zero PII) for Privacy Shield training.

Template-based generation of examples that contain NO personally identifiable
information, training the model to output [] when no PII is present.

Usage:
    python -m dataset.hard_negatives_generator
    python -m dataset.hard_negatives_generator --seed 42 --target-count 2000
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Template categories
# ──────────────────────────────────────────────────────────────────────

PUBLIC_FACTS = [
    "La pizza margherita è stata inventata a Napoli nel 1889.",
    "Il Colosseo è stato costruito tra il 72 e l'80 d.C.",
    "L'Italia è una repubblica parlamentare dal 1946.",
    "La Torre di Pisa pende di circa 3,97 gradi.",
    "Il Monte Bianco è la vetta più alta delle Alpi con i suoi 4.808 metri.",
    "La Divina Commedia è un poema allegorico composto tra il 1304 e il 1321.",
    "Roma è la capitale d'Italia dal 1871.",
    "Il lago di Garda è il lago più grande d'Italia.",
    "La lingua italiana deriva dal latino volgare.",
    "L'Etna è il vulcano attivo più alto d'Europa.",
    "La Costituzione italiana è entrata in vigore il primo gennaio 1948.",
    "Il Rinascimento italiano ebbe inizio a Firenze nel XIV secolo.",
    "L'Italia ha vinto quattro Mondiali di calcio: 1934, 1938, 1982 e 2006.",
    "La Sardegna è la seconda isola più grande del Mediterraneo.",
    "Il fiume Po è lungo 652 chilometri.",
    "Venezia è costruita su 118 piccole isole.",
    "Il Festival di Sanremo si tiene ogni anno dal 1951.",
    "L'Italia è il quinto paese più visitato al mondo.",
    "La Fiat fu fondata a Torino nel 1899.",
    "La Gioconda è un dipinto a olio su tavola di legno di pioppo realizzato intorno al 1503.",
    "Il sistema sanitario nazionale italiano è stato istituito nel 1978.",
    "L'Italia confina con Francia, Svizzera, Austria e Slovenia.",
    "La Serie A è il massimo campionato di calcio italiano.",
    "Il Vesuvio è alto 1.281 metri sul livello del mare.",
    "L'euro è la valuta italiana dal primo gennaio 2002.",
    "La Sicilia è la più grande isola del Mediterraneo.",
    "Il Parlamento italiano è composto da Camera e Senato.",
    "La pasta è stata introdotta in Italia attraverso la Sicilia.",
    "Il carnevale di Venezia risale al XII secolo.",
    "L'Accademia della Crusca fu fondata a Firenze nel 1583.",
]

DEFINITIONS = [
    "Il codice fiscale è un identificativo alfanumerico di 16 caratteri.",
    "Il GDPR è il Regolamento Generale sulla Protezione dei Dati dell'Unione Europea.",
    "L'IBAN è un codice internazionale per identificare un conto bancario.",
    "La PEC è la posta elettronica certificata, obbligatoria per le imprese italiane.",
    "Lo SPID è il Sistema Pubblico di Identità Digitale.",
    "Il CIE è la Carta d'Identità Elettronica.",
    "L'ISEE è l'Indicatore della Situazione Economica Equivalente.",
    "La partita IVA è un codice numerico di 11 cifre.",
    "Il REA è il Repertorio Economico Amministrativo.",
    "Il TFR è il Trattamento di Fine Rapporto.",
    "La CU è la Certificazione Unica rilasciata dai sostituti d'imposta.",
    "L'IMU è l'Imposta Municipale propria sugli immobili.",
    "Il CAF è il Centro di Assistenza Fiscale.",
    "La SCIA è la Segnalazione Certificata di Inizio Attività.",
    "Il 730 è il modello di dichiarazione dei redditi per dipendenti e pensionati.",
    "La TARI è la tassa sui rifiuti gestita dai comuni.",
    "Il durc è il Documento Unico di Regolarità Contributiva.",
    "Lo SDI è il Sistema di Interscambio per la fatturazione elettronica.",
    "Il MES è il Meccanismo Europeo di Stabilità.",
    "La NASPI è l'indennità di disoccupazione per i lavoratori dipendenti.",
]

BRANDS_PRODUCTS = [
    "Ho comprato un iPhone 15 da Apple ieri.",
    "La nuova Fiat 500 elettrica ha un'autonomia di 320 km.",
    "Netflix ha aumentato il prezzo dell'abbonamento premium.",
    "Ho ordinato un pacco su Amazon con consegna Prime.",
    "Il MacBook Pro con chip M3 è molto veloce.",
    "Samsung ha presentato il nuovo Galaxy S25.",
    "Ho scaricato l'app di PosteItaliane per i pagamenti.",
    "Spotify ha 200 milioni di abbonati nel mondo.",
    "La PlayStation 5 è ancora difficile da trovare in negozio.",
    "Ho preso un caffè da Starbucks prima della riunione.",
    "Il nuovo modello di Tesla ha il pilota automatico.",
    "Microsoft ha rilasciato Windows 12 con l'intelligenza artificiale integrata.",
    "Mediaworld ha uno sconto del 30% sulle lavatrici.",
    "La Vespa è uno dei simboli del made in Italy.",
    "Google ha aggiornato l'algoritmo di ricerca questo mese.",
    "Ho comprato le scarpe Nike in offerta su Zalando.",
    "Il Thermomix prepara ricette in automatico.",
    "Esselunga consegna la spesa a casa in giornata.",
    "WhatsApp ha introdotto le community per gruppi tematici.",
    "La nuova Alfa Romeo Tonale è un SUV ibrido.",
]

GENERIC_REFERENCES = [
    "Secondo il GDPR, l'articolo 15 prevede il diritto di accesso ai dati personali.",
    "La normativa sulla privacy richiede il consenso esplicito per il trattamento dei dati.",
    "Il garante della privacy ha emesso nuove linee guida sulla protezione dei dati.",
    "L'informativa sulla privacy deve essere chiara e comprensibile.",
    "Il titolare del trattamento è responsabile della sicurezza dei dati.",
    "Il diritto all'oblio è sancito dall'articolo 17 del GDPR.",
    "La notifica di data breach deve avvenire entro 72 ore.",
    "Il registro dei trattamenti è obbligatorio per tutte le aziende con più di 250 dipendenti.",
    "Il DPO è il Responsabile della Protezione dei Dati.",
    "Le sanzioni GDPR possono arrivare fino al 4% del fatturato annuo.",
    "La base giuridica del trattamento può essere il consenso o il legittimo interesse.",
    "I dati sensibili richiedono misure di protezione rafforzate.",
    "La profilazione automatizzata è soggetta a restrizioni specifiche.",
    "Il trasferimento di dati extra UE richiede garanzie adeguate.",
    "La valutazione d'impatto è necessaria per trattamenti ad alto rischio.",
]

GENERIC_MEDICAL = [
    "L'influenza è una malattia virale stagionale che colpisce milioni di persone.",
    "Il vaccino antinfluenzale è consigliato per gli over 65.",
    "La vitamina D è importante per la salute delle ossa.",
    "Lo stress cronico può causare problemi cardiovascolari.",
    "La dieta mediterranea è considerata tra le più salutari al mondo.",
    "Il colesterolo alto è un fattore di rischio per le malattie cardiache.",
    "L'attività fisica regolare riduce il rischio di diabete.",
    "Il sistema immunitario protegge l'organismo dalle infezioni.",
    "La pressione arteriosa ottimale è sotto i 120/80 mmHg.",
    "Il sonno insufficiente è collegato a problemi di memoria.",
    "I probiotici aiutano a mantenere l'equilibrio della flora intestinale.",
    "La celiachia colpisce circa l'1% della popolazione.",
    "Il fumo è la principale causa di tumore ai polmoni.",
    "La prevenzione è fondamentale per ridurre l'incidenza di molte malattie.",
    "Il medico di base è il primo riferimento per la salute del paziente.",
    "L'aspirina ha proprietà antinfiammatorie e antipiretiche.",
    "La salute mentale è importante quanto quella fisica.",
    "Il sistema sanitario nazionale garantisce assistenza a tutti i cittadini.",
    "Le allergie alimentari sono in aumento negli ultimi decenni.",
    "Il pronto soccorso gestisce le emergenze mediche 24 ore su 24.",
]

PUBLIC_FIGURES = [
    "Il presidente della Repubblica ha dichiarato lo stato di emergenza.",
    "Il primo ministro ha presentato la legge di bilancio in Parlamento.",
    "Il Papa ha tenuto l'udienza generale in piazza San Pietro.",
    "Il presidente del Consiglio ha incontrato i leader europei.",
    "Il ministro della salute ha annunciato nuove misure sanitarie.",
    "Il sindaco ha inaugurato il nuovo parco cittadino.",
    "Il governatore della regione ha firmato l'ordinanza.",
    "Il presidente della Camera ha aperto la seduta parlamentare.",
    "Il capo della polizia ha presentato il rapporto annuale.",
    "Il commissario europeo ha proposto nuove direttive.",
    "L'ambasciatore ha partecipato alla cerimonia ufficiale.",
    "Il prefetto ha convocato il comitato per l'ordine pubblico.",
    "Il questore ha disposto il rafforzamento dei controlli.",
    "Il presidente della Corte Costituzionale ha letto la sentenza.",
    "Il portavoce del governo ha rilasciato una dichiarazione ufficiale.",
]

CULTURAL_GEOGRAPHIC = [
    "La costiera amalfitana è patrimonio UNESCO dal 1997.",
    "Il Palio di Siena si corre due volte l'anno in Piazza del Campo.",
    "La mozzarella di bufala campana è un prodotto DOP.",
    "I trulli di Alberobello sono un esempio unico di architettura pugliese.",
    "Il tartufo bianco d'Alba è uno dei prodotti più pregiati al mondo.",
    "La vendemmia in Toscana si svolge generalmente tra settembre e ottobre.",
    "Le Cinque Terre sono cinque borghi sulla costa ligure.",
    "Il Brunello di Montalcino è uno dei vini italiani più prestigiosi.",
    "Le Dolomiti sono state dichiarate patrimonio UNESCO nel 2009.",
    "Il limoncello è un liquore tipico della costiera sorrentina.",
    "I Sassi di Matera sono abitazioni rupestri risalenti al Paleolitico.",
    "La Scala di Milano è uno dei teatri d'opera più famosi al mondo.",
    "Il Parmigiano Reggiano è stagionato per almeno 12 mesi.",
    "La grotta azzurra di Capri è una delle attrazioni più visitate d'Italia.",
    "Il Prosecco è prodotto nelle colline di Conegliano e Valdobbiadene.",
    "La focaccia genovese è un pane piatto condito con olio d'oliva.",
    "I Faraglioni di Capri sono tre formazioni rocciose nel mare.",
    "Il Ponte Vecchio di Firenze è il ponte più antico della città.",
    "La nduja è un salume spalmabile tipico della Calabria.",
    "Il Lago di Como è circondato da ville storiche e giardini.",
]

GENERIC_BUSINESS = [
    "L'azienda ha fatturato 10 milioni di euro nel 2025.",
    "Il mercato immobiliare italiano è in ripresa.",
    "Le esportazioni di prodotti alimentari sono cresciute del 12%.",
    "Il tasso di disoccupazione è sceso al 7,2% nell'ultimo trimestre.",
    "Le piccole e medie imprese rappresentano il 95% del tessuto produttivo italiano.",
    "Il PIL italiano è cresciuto dell'1,5% rispetto all'anno precedente.",
    "Il settore turistico contribuisce al 13% del PIL nazionale.",
    "Le startup innovative italiane sono oltre 14.000.",
    "Il mercato e-commerce in Italia vale 75 miliardi di euro.",
    "L'industria manifatturiera è il secondo settore per contributo al PIL.",
    "Le zone economiche speciali offrono agevolazioni fiscali alle imprese.",
    "Il credito d'imposta per la ricerca è pari al 20% delle spese.",
    "La transizione digitale è una priorità del PNRR.",
    "Il settore agroalimentare impiega 1,4 milioni di lavoratori.",
    "Le rinnovabili coprono il 40% del fabbisogno energetico nazionale.",
    "Il bonus edilizio ha generato investimenti per 70 miliardi.",
    "La logistica è un settore in forte crescita grazie all'e-commerce.",
    "Il mercato del lavoro richiede sempre più competenze digitali.",
    "Gli investimenti esteri in Italia sono in aumento.",
    "La bilancia commerciale italiana è in attivo per 50 miliardi.",
]


ALL_CATEGORIES = {
    "public_facts": PUBLIC_FACTS,
    "definitions": DEFINITIONS,
    "brands_products": BRANDS_PRODUCTS,
    "generic_references": GENERIC_REFERENCES,
    "generic_medical": GENERIC_MEDICAL,
    "public_figures": PUBLIC_FIGURES,
    "cultural_geographic": CULTURAL_GEOGRAPHIC,
    "generic_business": GENERIC_BUSINESS,
}


def generate_hard_negatives(
    output_dir: Path,
    seed: int = 42,
    target_count: int = 2000,
) -> None:
    """Generate hard-negative examples with zero PII entities."""
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect all templates
    all_templates: list[tuple[str, str]] = []
    for category, templates in ALL_CATEGORIES.items():
        for t in templates:
            all_templates.append((category, t))

    # If we need more than available templates, we will repeat with variations
    examples: list[dict] = []
    category_counts: dict[str, int] = {cat: 0 for cat in ALL_CATEGORIES}

    if target_count <= len(all_templates):
        # Sample without replacement
        selected = rng.sample(all_templates, target_count)
        for category, text in selected:
            examples.append({"text": text, "entities": []})
            category_counts[category] += 1
    else:
        # Use all templates first
        for category, text in all_templates:
            examples.append({"text": text, "entities": []})
            category_counts[category] += 1

        # Fill remaining with variations
        remaining = target_count - len(all_templates)
        variation_prefixes = [
            "In generale, ", "Come è noto, ", "È importante sapere che ",
            "Va ricordato che ", "Secondo le statistiche, ",
            "Come tutti sanno, ", "È un fatto che ", "Bisogna sapere che ",
            "Da notare che ", "Per la cronaca, ",
        ]
        variation_suffixes = [
            "", " Questo è un dato pubblico.", " Lo dice la normativa.",
            " È un fatto noto.", " Si tratta di informazione pubblica.",
            " È un dato ufficiale.", " Questo è risaputo.",
        ]

        for _ in range(remaining):
            category, base_text = rng.choice(all_templates)
            prefix = rng.choice(variation_prefixes)
            suffix = rng.choice(variation_suffixes)

            # Avoid double period
            if base_text.endswith(".") and suffix.startswith("."):
                suffix = suffix[1:]

            varied_text = f"{prefix}{base_text[0].lower()}{base_text[1:]}{suffix}"
            examples.append({"text": varied_text, "entities": []})
            category_counts[category] += 1

    # Shuffle
    rng.shuffle(examples)

    # Save
    output_path = output_dir / "hard_negatives.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    # Print stats
    print(f"\n{'=' * 60}")
    print(f"Hard Negatives Generation Complete")
    print(f"  Total examples: {len(examples):,}")
    print(f"  Category breakdown:")
    for category, count in sorted(category_counts.items()):
        print(f"    {category:25s}: {count:,}")
    print(f"  Output: {output_path}")
    print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate hard-negative (zero-PII) examples for Privacy Shield training."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/synthetic"),
        help="Output directory for hard negatives (default: data/synthetic)",
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
        default=2000,
        help="Target number of hard-negative examples (default: 2000)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    generate_hard_negatives(args.output_dir, args.seed, args.target_count)


if __name__ == "__main__":
    main()
